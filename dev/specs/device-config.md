# Device config

## Overview

kohle needs two kinds of configuration, and they must not share a home.
**Ledger settings** are facts about the books, such as the Bundesland. They
live in the `settings` table, are audited, and travel with every copy of the
ledger. **Device settings** are facts about one machine: where its ledger
is, and later its role, how long it waits for a lock, and where its backups
go. They must never travel with a copy, because a synced snapshot would
overwrite them. Today a device setting can only be an environment variable
(`KOHLE_DB`). `init.toml` is read once by `init` and never again. This feature
adds a per-device config file that the user edits by hand, in the spirit of
git config or ranger's `rifle.conf`. It also adds two read-only commands to
inspect the file, and the file's first key, `ledger.path`.
`device-topology-and-sync`, `configurable-net-worth-sampling` and
`budgeting` add their device keys through this mechanism and must not invent
another.

## Goals

- **One file, edited by hand.** The file is
  `$XDG_CONFIG_HOME/kohle/config.toml`, falling back to
  `~/.config/kohle/config.toml` when `XDG_CONFIG_HOME` is unset. No other
  file is read and nothing is merged.
  - The format is TOML. Keys are named by dotted path. `[ledger]` /
    `path = "…"` and `ledger.path = "…"` are equivalent.
  - kohle never writes the file.
  - The file is read once per command, before any engine is created.
- **A missing file is not an error.** Every key then takes its default.
- **Fixed key registry.** Device keys come from a fixed list in the code, and
  each key has its own value validator. This is the same pattern as the
  ledger `SETTINGS` registry, but a separate registry. An unknown key or an
  invalid value makes every command except `--help` exit non-zero before
  doing anything. That includes `init` and `migrate`. The error is one line
  naming the file, the key, and either the known keys or the valid values.
  TOML syntax errors are reported the same way. Testable: a config with
  `ledgr.path = "/x"` makes `list-accounts` exit non-zero naming the file
  and listing `ledger.path`, and `kohle-cli --help` still works.
- **Precedence: built-in default < config file < an existing environment
  variable.** No new environment variables and no command-line flags are
  added for any key.
- **`ledger.path` is the first key.** The ledger is resolved from `KOHLE_DB`
  if set, else from `ledger.path`, else from
  `$XDG_DATA_HOME/kohle/kohle.db` (falling back to
  `~/.local/share/kohle/kohle.db`).
  - The same resolution is used by `kohle-cli`, `kohle-tui` and the repo's
    Alembic environment.
  - A leading `~` is expanded.
  - A relative path is rejected by the validator, because a cwd-relative
    ledger is what app-initialization removed.
  - The validator checks form only. A path with no ledger behind it is
    reported by the existing "no ledger at <path>; run `kohle-cli init`"
    check.

  Testable, with `XDG_CONFIG_HOME` and `XDG_DATA_HOME` pointing at temp
  dirs:
  - with `ledger.path` set and `KOHLE_DB` unset, commands use `ledger.path`;
  - with both set, `KOHLE_DB` wins;
  - with neither set, the XDG default is used;
  - `ledger.path = "kohle.db"` is rejected.
- **`config list`** prints every known device key with its effective value
  and where the value came from: `default`, `file`, or the overriding
  environment variable (`KOHLE_DB`).
- **`config get <key>`** prints the effective value of one key. An unknown
  key exits non-zero and lists the known keys.
- **Both config commands never open the ledger** and skip the schema-version
  check. They work when the ledger is missing, behind or ahead of the code,
  so they are the way to debug a wrong `ledger.path`. Testable: with
  `ledger.path` pointing at a nonexistent file, `config list` exits 0 and
  shows the path.
- **Ledger settings stay where they are.**
  - `list-settings` still shows only ledger settings, the ledger path and
    the revision. Its path line now also shows the path's source.
  - `set-setting` stays ledger-only. Given a device key, it refuses with
    "`<key>` is a device key; edit <config path>".
- **`init.toml` keeps its role.** It stays `init`'s one-time input and is not
  merged into `config.toml`.
- **Tests never read the real per-user config.** Every test that runs a
  command points `XDG_CONFIG_HOME` at a temp dir, as the `init.toml` tests
  already do.
- **README documents** the file's location, its TOML format and dotted keys,
  the key list (`ledger.path` for now), the precedence, the `config`
  commands, and the split between ledger settings (the table, travel with
  the ledger) and device settings (the file, stay on the machine).

## Non-Goals

- **`config set` / `config unset`**, and the `tomlkit` dependency that
  editing TOML without losing comments would need. The file is edited by
  hand. A setter can be added later without changing anything else.
- **Plugin settings in the file.** `KOHLE_PRICE_FILE` and
  `KOHLE_ALPHAVANTAGE_KEY` stay environment variables. Moving them would
  mean plugins registering their own keys, and it would put an API key in a
  file the user is encouraged to edit and share. No secrets go in the file.
- **More than one config file:** no system-wide `/etc` file, no
  project-local file, no merging, no includes.
- **A new environment variable or flag per key**, and no `KOHLE_CONFIG`
  override of the file's path. Tests isolate the file through
  `XDG_CONFIG_HOME`.
- **Live reload.** The file is read once per command.
- **The role, lock-wait and backup keys.** They are owned by
  `device-topology-and-sync`, which adds them to this registry.

## Technical Approach

- Python 3.12, read with the standard library's `tomllib`. No new
  dependencies.
- The device-key registry mirrors `kohle/use_cases/settings.py`: each key
  maps to a validator returning `Result`. Errors are domain error values,
  not raised exceptions.
- `ledger_path()` in `kohle/db/connection.py` gains the file as a middle
  source. The config is loaded and validated before the path is resolved.
- The `config` commands sit outside the `_LedgerCommand` schema check, like
  `init` and `migrate`. Unlike them, they also never resolve an engine.

## Dependencies

**The frozen `app-initialization` spec must be amended by the user before
implementation.** No agent may edit `dev/specs/`. The steps:

1. Unfreeze it:
   `git mv dev/specs/app-initialization.md dev/inbox/app-initialization.md`
2. **Amendment 1: two configuration scopes, not one.** Its Overview says
   `configurable-net-worth-sampling` and `budgeting` "build on this settings
   mechanism and must not invent a second one". Its Goals say "Settings live
   in the ledger … never in environment variables". Replace that framing
   with: *ledger settings live in the `settings` table; device settings live
   in `config.toml` (`device-config`); neither scope invents a further
   mechanism.* The Non-Goal "The init file as runtime configuration" stays
   true. Optionally, add that changing a device setting means editing
   `config.toml`.
3. **Amendment 2: `ledger.path` joins path resolution.** The Goal "One
   database location" becomes: `KOHLE_DB` if set, else `ledger.path` from
   `config.toml`, else the XDG default. "`KOHLE_DB` is the only environment
   variable that selects the database" stays true. "`XDG_CONFIG_HOME` and
   `HOME` are read only to find the init file" becomes "… to find the init
   file and `config.toml`".
4. Refreeze it:
   `git mv dev/inbox/app-initialization.md dev/specs/app-initialization.md`

The user can make these edits, or have `product-owner` make them while the
file sits in `dev/inbox/`.

**Note handed to `device-topology-and-sync`.** A missing config file means
every key takes its default. The default chosen there for the device role
therefore decides what a reader becomes if its `config.toml` disappears or
fails to sync. With a default of `writer`, a reader that loses its file
silently opens its snapshot read-write. That feature must choose the default
with this in mind.

## Open Questions

None blocking. Left to design:

- Where the device-key registry lives inside `kohle/`.
- The exact output layout of `config list`, and how `list-settings` shows the
  path's source.
