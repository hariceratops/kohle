# Getting started

Installing kohle, creating a ledger and the first commands.

## Install

Install the application into a uv environment, activate it and run it:

<!-- docs: illustration -->
```sh
uv init
uv sync
source .venv/bin/activate
kohle-cli
```

kohle is a command line tool. `kohle-cli` is the entry point used throughout
this guide, and every option of every command is listed in the
[command reference](reference.md).

## Where the ledger lives

Every entry point (`kohle-cli`, `kohle-tui` and the `alembic` command) finds
the ledger the same way, whatever the working directory:

1. `KOHLE_DB`, if set and non-empty;
2. else `ledger.path` in the [device config](#device-config);
3. else `$XDG_DATA_HOME/kohle/kohle.db`;
4. else `~/.local/share/kohle/kohle.db`.

There is no `--db` flag. `kohle-cli get-config ledger.path` prints the path
that will be used, and `kohle-cli list-config` also says which of the rules
above chose it.

## Device config

Settings that describe one machine live in
`$XDG_CONFIG_HOME/kohle/config.toml`, or `~/.config/kohle/config.toml` when
`XDG_CONFIG_HOME` is unset. kohle reads the file once per command and never
writes it. A missing file means every key takes its default.

The file is TOML. `[ledger]` with `path = "..."` and `ledger.path = "..."` are
equivalent. There are two keys:

- `ledger.path` is where the ledger is, an absolute path or one starting with
  `~`. `KOHLE_DB` overrides it.
- `ledger.mode` is `writer` (the default) or `reader`, case-sensitive. A
  reader opens the ledger read-only, never creates it, and refuses every
  command that writes. See [Several devices](several-devices.md).

<!-- docs: file ~/.config/kohle/config.toml -->
```toml
[ledger]
path = "~/books/kohle.db"
mode = "reader"
```

With that file in place, `list-config` prints every device key with its
effective value, where the value came from (`default`, `file` or `KOHLE_DB`),
and the config file it read. Neither `list-config` nor `get-config` opens the
ledger, so they work when it is missing or out of date. They are the way to
debug a wrong `ledger.path`. The ledger this file points to does not exist, so
a reader refuses to go on:

<!-- docs: first-run uses ~/.config/kohle/config.toml -->
```console
$ kohle-cli list-config
ledger.path = ~/books/kohle.db  (file)
ledger.mode = reader  (file)

file: ~/.config/kohle/config.toml
$ kohle-cli get-config ledger.mode
reader
$ kohle-cli list-accounts
Error: no ledger at ~/books/kohle.db; this device is configured as a reader and never creates one
```

For a key the built-in default applies first, then the file, then `KOHLE_DB`
(for `ledger.path` only; there are no other environment overrides).

There are two scopes of setting. Ledger settings live in the ledger, travel
with it and are managed with `list-settings` and `set-setting`. Device settings
live in the config file and stay on the machine. Keep secrets out of the file;
plugin variables such as `KOHLE_ALPHAVANTAGE_KEY` stay environment variables.

An unknown key, an invalid value, a TOML syntax error or an unreadable file
stops every command, `init` and `migrate` included, with one line naming the
file. Only `--help` still works.

## First run

`kohle-cli init` creates the ledger. It takes no flags and never prompts. Its
only input is the init file, `$XDG_CONFIG_HOME/kohle/init.toml`, or
`~/.config/kohle/init.toml` when `XDG_CONFIG_HOME` is unset.

The file is TOML. The only key is `state`, your Bundesland, whose public
holidays are not working days:

<!-- docs: file ~/.config/kohle/init.toml -->
```toml
state = "BW"
```

The valid codes are `BB BE BW BY HB HE HH MV NI NW RP SH SL SN ST TH`. An
unknown key, an invalid `state`, a missing file or a file without `state` makes
`init` exit non-zero and create nothing.

Before the first `init`, no ledger exists and every other command says so:

<!-- docs: first-run -->
```console
$ kohle-cli list-accounts
Error: no ledger at ~/.local/share/kohle/kohle.db; run `kohle-cli init`
```

Now create it and look at the settings:

<!-- docs: first-run uses ~/.config/kohle/init.toml -->
```console
$ kohle-cli init
Initialized ledger at ~/.local/share/kohle/kohle.db, revision d7f3b9a1c846
$ kohle-cli list-settings

ledger:   ~/.local/share/kohle/kohle.db  (default)
revision: d7f3b9a1c846
$ kohle-cli list-config
ledger.path = ~/.local/share/kohle/kohle.db  (default)
ledger.mode = writer  (default)

file: ~/.config/kohle/config.toml (not found)
```

`init` creates the ledger's directory, runs the packaged migrations and
records the file's `state` as the ledger's `start` Bundesland. It reads the
file once, so editing it afterwards changes nothing. `list-settings` shows
every setting (a fresh ledger has none), then the ledger path with how it was
chosen, and its schema revision. The revision changes whenever kohle gains a
migration, so yours may differ from the one shown here.

Run against an existing ledger, `init` never writes:

- at the current revision, with the file's `state` equal to the `start`
  entry, it says `already initialized` and exits 0;
- behind, it exits non-zero and points to `migrate`;
- with a `start` state that differs or is missing, it exits non-zero and
  points to `move-state --from start <code>`.

A failed or interrupted first `init` leaves no ledger.

`set-setting <key> <value>` changes a ledger setting after `init`. `state` is
not a setting, and `set-setting state` points to `move-state`:

```console
$ kohle-cli set-setting state BY
Error: state is not a setting; record a move with `kohle-cli move-state --from <start|YYYY-MM-DD> <code>`
```

An unknown key lists the known keys and an invalid value lists the valid
ones. Either exits non-zero and writes nothing. A device key such as
`ledger.path` is refused with a pointer to the config file; edit that file
instead.

## Schema check

Every command except `init`, `migrate` and `--help` first checks the ledger's
schema revision, reads and writes alike. It only reads and never creates a
file. Three outcomes stop the command with one line and a non-zero exit:

- no file at the path, as shown above: ``no ledger at <path>; run `kohle-cli init` ``;
- revision behind this kohle: the line names both revisions and says to run
  `kohle-cli migrate`;
- revision ahead, meaning a ledger from a newer kohle: the line says to
  upgrade kohle.

Several kohle processes on one machine (a scheduled `fetch-prices` and an
import, say) are serialised by SQLite. A command that finds the ledger locked
by another writer waits up to 30 seconds for it. If the lock is still held, the
command stops with `the ledger stayed locked by another process; nothing was
changed, try again` and a non-zero exit. This applies in both modes.

## Upgrading the ledger

`kohle-cli migrate` brings a ledger that is behind this kohle's revision up to
it. It takes no flags. It copies the ledger to a hidden file beside it,
applies the packaged migrations to the copy, and renames the copy over the
ledger. A failed or interrupted `migrate` therefore leaves the ledger at its
previous revision with its data unchanged. A hard kill can leave a stray
`.kohle.db.XXXX.tmp` in the data directory; it is never read and may be
deleted. The ledger file ends up mode 0600, and a symlinked ledger is upgraded
where it lives and stays a link.

Run it after upgrading kohle, when the schema check tells you the ledger is
behind. On a ledger that is already current it only says so:

```console
$ kohle-cli migrate
ledger at ~/.local/share/kohle/kohle.db is already at revision d7f3b9a1c846
```

The other outcomes cannot be shown from a fresh ledger:

- no file at the path: it points to `kohle-cli init`, creates nothing and
  exits 1;
- revision ahead of this kohle: it says to upgrade kohle and exits 1.

A ledger migrated from before settings existed has no `start` Bundesland, and
`net-worth-history` refuses without one. Record it with
`move-state --from start <code>`.
