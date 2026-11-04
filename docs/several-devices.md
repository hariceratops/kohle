# Several devices

Using one ledger from more than one device.

If you use kohle on one machine and keep no copies of the ledger, you can skip
this page.

## The model

One device holds the writable ledger, the writer. Other devices read a copy of
it, and are readers. `kohle-cli snapshot` makes the copy, and `ledger.mode =
"reader"` in a device's [config](getting-started.md#device-config) keeps that
copy read-only.

The one-writer rule comes from copying a file between devices, not from kohle.
File sync tools produce conflict copies, not merges, when two devices write the
same file. Network filesystems lock unreliably, so SQLite's lock cannot
serialise writers on different machines.

This is the strategy kohle supports. A server layer in front of SQLite
(rqlite, LiteFS, libSQL) or a synced operation log are possible later options,
and neither is built.

## Making a copy

`kohle-cli snapshot <path>` writes a consistent, self-contained copy of the
ledger to `<path>`. The copy opens as an ordinary ledger, with no journal or
WAL file beside it. The ledger itself is only read: nothing is changed and no
operation is recorded. The command gets the same
[schema check](getting-started.md#schema-check) as the others, so a missing,
behind or ahead ledger stops it with the usual line.

```console
$ kohle-cli snapshot ~/copy.db
Wrote a snapshot of ~/.local/share/kohle/kohle.db to ~/copy.db
```

`<path>` may be anywhere, but it must not exist and its parent directory must.
A file (even an empty one), a directory or a symlink at `<path>` is refused
with a non-zero exit, and nothing is overwritten:

```console
$ kohle-cli snapshot ~/copy.db
Wrote a snapshot of ~/.local/share/kohle/kohle.db to ~/copy.db
$ kohle-cli snapshot ~/copy.db
Error: ~/copy.db already exists; snapshot never overwrites a file
$ kohle-cli snapshot ~/missing/copy.db
Error: writing a snapshot to ~/missing/copy.db failed: No such file or directory
```

The copy is written to a hidden `.<name>.XXXX.tmp` beside `<path>` and renamed
into place, so `<path>` is never half-written. A hard kill can leave that
temporary file, which is never read and may be deleted. The snapshot file is
mode 0600.

## Moving the copy

Moving the copy is up to you. A sync tool such as Syncthing, a scheduled
`rsync` pull or a plain file copy all work. Making the transport one-way, so
that readers only receive, is what keeps a reader from ever writing back.

A scheduled job should not snapshot straight onto the last copy, because
`snapshot` refuses an existing path. Write to a temporary name and rename it
over the old copy. A cron entry could run this on the writer, with `~/Sync/kohle`
standing for the folder your sync tool watches:

<!-- docs: illustration -->
```sh
rm -f ~/Sync/kohle/.kohle.db.new
kohle-cli snapshot ~/Sync/kohle/.kohle.db.new && mv ~/Sync/kohle/.kohle.db.new ~/Sync/kohle/kohle.db
```

The job can run `kohle-cli fetch-prices` first, so each copy carries the
latest prices. It uses shell operators, so the checker does not run it.

## Setting up a reader

In the reader's config, point `ledger.path` at the copy and set the mode. See
[Device config](getting-started.md#device-config) for where the file lives and
how the keys resolve:

<!-- docs: file ~/.config/kohle/config.toml -->
```toml
[ledger]
path = "~/Sync/kohle/kohle.db"
mode = "reader"
```

A reader opens the ledger file read-only. Reads work normally: `balance`,
`list-accounts` and the reports. Anything that writes is refused up front,
before it does anything, and the refusal names the config file. That covers
`init`, `migrate`, `record`, the imports, `set-setting`, `fetch-prices` and the
rest. `snapshot` only reads, so it still works on a reader.

The examples below use a config file with only the mode, since the example
ledger is found by the default rules:

<!-- docs: file ~/.config/kohle/config.toml -->
```toml
[ledger]
mode = "reader"
```

<!-- docs: uses ~/.config/kohle/config.toml -->
```console
$ kohle-cli list-accounts
account    type    iban
---------  ------  ------
People     asset   -
$ kohle-cli add-account Checking --type asset
Error: this device is configured as a reader; `ledger.mode` is set in ~/.config/kohle/config.toml
$ kohle-cli migrate
Error: this device is configured as a reader; `ledger.mode` is set in ~/.config/kohle/config.toml
```

A reader never creates the ledger either. If the file at `ledger.path` is
missing, the command says so and creates nothing. A copy from a newer kohle is
reported as ahead: upgrade kohle on the reader. A reader never runs `migrate`,
so after upgrading kohle on the writer, make a fresh snapshot.

The mode depends only on the key. Any ledger file can be opened read-only,
whether or not it came from `snapshot`, and there is no environment override.

## Limits and caveats

- Nothing in kohle stops a second device from being configured as a writer,
  and a reader whose `config.toml` is missing falls back to `writer`. The
  guarantee comes from the one-way transport, the device configuration and file
  permissions, not from coordination between devices.
- `chmod 444` on a reader's copy is a backstop: even a plain open of the file
  cannot write it.
- Reader copies are not backups. A corruption on the writer syncs out to every
  reader.
- Keep `config.toml` out of synced folders: it describes one device.
- Point readers at a snapshot, not at a live file another process writes.
