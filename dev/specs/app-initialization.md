# First-run initialization

## Overview

kohle has no `init` command. On an empty directory, `kohle-cli list-accounts`
fails with a raw SQLAlchemy `no such table` error. The only way to get a
schema is to run `alembic upgrade head` from the repo root, and the README
never mentions it. The database path is hard-coded as `sqlite:///kohle.db`,
relative to the current directory, in both `kohle/db/connection.py` and
`alembic.ini`. So which ledger a command touches depends on where it is run.
This feature adds:

- a fixed per-user database location;
- `init`, which creates a ledger by running the migrations shipped with the
  package, and `migrate`, which upgrades an existing ledger;
- a schema-version check before every command, so a missing or out-of-date
  database gives one clear message instead of a stack trace;
- a settings table in the ledger. Its first setting is the Bundesland, which
  `init` requires;
- a per-user init file, `init.toml`, which is `init`'s only input. `init`
  copies its values into the settings table once, and nothing reads the file
  after that.

Ledger settings live in this settings table; device settings live in
`config.toml`, defined by `device-config`. `configurable-net-worth-sampling`
and `budgeting` build on these two and must not invent a third mechanism.

## Goals

- **One database location, independent of the working directory.** The path
  is `KOHLE_DB` if set, else `ledger.path` from `config.toml`
  (`device-config`). Otherwise it is `$XDG_DATA_HOME/kohle/kohle.db`,
  falling back to `~/.local/share/kohle/kohle.db` when `XDG_DATA_HOME` is
  unset. There is no `--db` flag. `KOHLE_DB` is the only environment
  variable that selects the database. `XDG_CONFIG_HOME` and `HOME` are read
  only to find the init file and `config.toml`, and no environment variable
  supplies a setting.
  Plugin variables (`KOHLE_PRICE_FILE`, `KOHLE_ALPHAVANTAGE_KEY`) are
  unaffected. The same
  path resolution is used by `kohle-cli`, `kohle-tui`, and the repo's Alembic
  environment, so `alembic revision --autogenerate` still works for writing
  migrations. Testable: with `KOHLE_DB` unset and `XDG_DATA_HOME` and
  `XDG_CONFIG_HOME` pointing at temp dirs, commands run from two different
  working directories read the same ledger.
- **Migrations ship with the package.** An installed `kohle-cli` can run
  `init` and `migrate` outside a checkout. They run the packaged migrations
  in code, never by shelling out to `alembic`. A database is valid only
  after every migration has run in order, because migrations add seed data
  (the `People` root). Tables are never created with `create_all`. Testable:
  after `init`, the recorded Alembic revision equals the code's head.
- **`init` reads its input from an init file.** `init` takes no flags and
  never prompts.
  - Its only input is `$XDG_CONFIG_HOME/kohle/init.toml`, falling back to
    `~/.config/kohle/init.toml` when `XDG_CONFIG_HOME` is unset. No other file
    is looked at (no `./.kohlerc`), and nothing is merged.
  - The file is TOML. The only key now is `state`, for example
    `state = "BW"`. Settings that a later feature requires at init are added
    as keys in this file.
  - Each key is checked with the same validator `set-setting` uses. An
    unknown key is an error that lists the known keys. An invalid `state` is
    an error that lists the valid codes, the same set as
    `kohle.use_cases.sampling.STATES`.
  - A missing file, or a file with no `state` key, makes `init` exit
    non-zero with a message naming the path it looked at.
  - `init` reads the file once and stores its values in the settings table.
    Nothing reads the file afterwards; the ledger is the single source of
    truth. Editing the file after `init` changes nothing; `set-setting` does.

  The file is read and validated before anything is created, so any file
  error leaves no database behind. On a path with no database, `init` then:
  1. creates the parent directory if needed;
  2. migrates to head;
  3. stores the settings from the file.

  Testable, with `KOHLE_DB` pointing at a fresh temp path and
  `XDG_CONFIG_HOME` at a temp dir:
  - with `kohle/init.toml` containing `state = "BW"`, `init` followed by
    `list-accounts` shows the `People` root, and the settings listing shows
    `state = BW`;
  - with no `kohle/init.toml`, `init` exits non-zero naming
    `<XDG_CONFIG_HOME>/kohle/init.toml`, and no file exists at `KOHLE_DB`;
  - with `state = "XX"`, or with an extra unknown key, `init` exits non-zero
    with the matching message, and no file exists at `KOHLE_DB`.
- **`init` on an existing database never writes to it.** The file's `state`
  is compared with the database. It works by the database's state:
  - At head, with a stored Bundesland equal to the file's `state`: it
    reports "already initialized at <path>, revision <rev>" and exits 0.
  - Behind head: it exits non-zero and points to `migrate`.
  - At head, with a stored Bundesland that differs from the file's `state`
    or is unset: it exits non-zero and points to the setter.
- **`migrate` upgrades an existing ledger to head.**
  - Already at head: it reports so and exits 0.
  - No database at the path: it exits non-zero and points to `init`.
  - Database newer than the code: it exits non-zero and says to upgrade
    kohle.
- **Schema-version check before every command.** It runs on every command
  except `init`, `migrate` and `--help`, reads and writes alike. Each case
  gets one line of message and a non-zero exit:
  - No file at the path: "no ledger at <path>; run `kohle-cli init`". No
    file is created, not even an empty one.
  - Revision behind head: points to `migrate`.
  - Revision ahead of head: says to upgrade kohle. This covers a snapshot
    from an upgraded Pi read by an older install.

  Testable: each case produces its message without a traceback.
- **The check never writes.** It only reads the stored revision. It works,
  and the connection setup works, on a `mode=ro` SQLite connection.
  Read-only mode itself belongs to `device-topology-and-sync`. This feature
  only makes sure nothing it adds stands in its way. Testable: the check
  succeeds against a `sqlite:///file:<path>?mode=ro&uri=true` URL of an
  up-to-date ledger.
- **Ledger settings live in the ledger.** Ledger settings are stored in a
  table in the database, never in environment variables. Device settings
  live in `config.toml` instead (`device-config`).
  - Keys come from a fixed list in the code, and each key has its own value
    validator. The only key now is `state`. Sampling and budgeting add
    theirs later.
  - `set-setting <key> <value>` writes a setting. An unknown key is an error
    that lists the known keys. An invalid value is an error that lists the
    valid values.
  - A listing command shows every known key with its value, or "unset". It
    also shows the database path and schema revision, either in the listing
    or in a small `status` command; design decides which.
  - Every change to a setting is recorded as an `Operation` in the audit
    trail and appears in `list-operations`.
  - The names follow the current flat verb-object style;
    `cli-command-naming` renames them later.
- **Existing ledgers stay honest.** The migration that adds the settings
  table leaves `state` unset. Nothing anywhere assumes `BY`.
- **`net-worth-history` reads the stored Bundesland.** `--state` loses its
  `BY` default and stays as an optional per-run override. With no override
  and no stored value, the command refuses and points to
  `set-setting state <code>`. Testable: on a ledger with `state` unset,
  `net-worth-history` without `--state` exits non-zero with that message;
  with `--state HE`, it runs.
- **All-or-nothing.** If `init` fails or is interrupted, it leaves no
  half-built database: either no file, or nothing a re-run of `init` would
  refuse. If `migrate` fails or is interrupted, the ledger keeps its
  previous revision and its data unchanged.
- **README documents** `init`, `migrate`, the per-user location, `KOHLE_DB`,
  the init file (its location, its TOML format and the `state` key), and the
  one-time manual move of an existing `./kohle.db`.

## Non-Goals

- **Reader / read-only mode**, and how a device is marked as a reader. Both
  are owned by `device-topology-and-sync`.
- **Sampling rules and their settings.** Owned by
  `configurable-net-worth-sampling`, including the long-term future of the
  `--state` override.
- **Base currency as a setting.** It stays the `BASE_CURRENCY` constant;
  making it configurable is `multi-currency-and-fx`. EUR is still created
  lazily on first record (`journal.py`), and `init` does not seed it.
- **Moving the existing ledger automatically.** The user moves it once by
  hand.
- **Automatic backups before `migrate`.** They belong to the backup question
  in `device-topology-and-sync`.
- **Renaming existing commands.** That is `cli-command-naming`.
- **Any `init` input other than the init file.** No flags, no interactive
  prompting, no project-local or system-wide config file, and no merging of
  several files.
- **The init file as runtime configuration.** Only `init` reads it. Changing
  a setting afterwards is `set-setting`'s job.

## Technical Approach

- Python 3.12, SQLAlchemy 2.0 and Alembic. Migrations and their environment
  move inside the `kohle` package, and their location is resolved from the
  package, not from `alembic.ini`. `init` and `migrate` drive Alembic through
  its Python API.
- Path resolution replaces the hard-coded `DATABASE_URL` in
  `kohle/db/connection.py`. It runs before any engine is used, because the
  path must be known before the database can be opened.
- SQLite creates an empty file when a missing path is opened in the default
  mode. So the check for a missing file has to happen without opening a
  writable connection on that path.
- The revision check compares the stored revision with the packaged head
  using reads only. Only `init` and `migrate` may create or update
  `alembic_version`.
- Settings writes go through the usual `UnitOfWork` and `crud_create`, so
  they are audited like any other write. The settings reads used by
  `net-worth-history` leave no `OperationGroup` behind.
- The init file is parsed with the standard library's `tomllib` (Python
  3.12), so no dependency is added. Its keys are validated against the same
  key list and per-key validators as `set-setting`, so a key added there for
  init is checked the same way in both places.
- The CLI's session-factory injection (`ctx.obj`) stays. Tests set
  `KOHLE_DB` or inject a factory, point `XDG_CONFIG_HOME` at a temp dir for
  the init file, and never touch the real per-user paths.

### Constraint recorded for `device-topology-and-sync`

The marker that tells a device it is a reader cannot be a value in the
settings table. A reader's database is a synced snapshot of the Pi's ledger,
so any stored value is overwritten by the next sync. The marker has to live
outside the ledger. This spec does not decide what it is.

## Open Questions

None blocking. Two choices are left to design:

- Whether the database path and revision appear in the settings listing or in
  a separate `status` command.
- Where inside `kohle/` the migrations live.
