# First-run initialization

## Goal

Give a new user one command that takes kohle from nothing to a usable ledger,
and make every other command say so plainly when that has not happened.

The problem behind it: there is no `init`. On an empty directory
`kohle-cli list-accounts` dies with a raw SQLAlchemy `no such table` error.
The only way to a schema is `alembic upgrade head` from the repo root, which
the README never mentions.

## Considerations surfaced

**The database moves to a per-user location.** `kohle.db` is hard-coded
relative to the current directory today, in both `kohle/db/connection.py` and
`alembic.ini`, so which ledger a command touches depends on where it is run.
Agreed direction: default to a fixed per-user path (`~/.local/share/kohle/`
style), overridable by `KOHLE_DB`. The database is not under source control
and the existing ledger is moved once by hand. `KOHLE_DB` is the only
environment variable, because the path must be known before the database can
be opened.

**Migrations ship with the package.** `alembic/` sits outside the `kohle`
package, so an installed `kohle-cli` cannot migrate outside a checkout. `init`
runs the packaged migrations programmatically.

**Seed data comes from migrations.** The `People` root is seeded by a
migration, and the base `EUR` unit presumably by an earlier one (unverified).
A fresh database is only valid after every migration has run in order.

**Settings live in the database.** Agreed direction: a settings table, not
environment variables. Settings belong to the ledger — the Bundesland that
salary-day sampling depends on should travel with the ledger, not the shell.
The sampling settings themselves are described in
`configurable-net-worth-sampling`.

**The Bundesland is required at init.** No default: `init` does not complete
without it. A required flag keeps `init` scriptable.

**Existing ledgers have no settings.** The migration that adds the settings
table cannot invent a Bundesland for a ledger created before it. It leaves the
value unset, and the commands that need it refuse with a message pointing to
the setter, rather than silently assuming one.

**Not-initialized and out-of-date databases.** Every command opens the
database; a missing schema, or one behind the code's head revision, should
produce one clear message instead of a stack trace. `todo.md` calls this the
"check in top".

## Directions rejected

- **Creating tables with `create_all` on first connect**: it bypasses Alembic
  and leaves the revision unrecorded, so later migrations cannot tell where
  the database stands.
- **Keeping `./kohle.db` as the default**: it is how a new user ends up in the
  wrong directory with an empty ledger; moving the one existing ledger once is
  cheaper than living with that.
- **Settings in environment variables**: they belong to the shell, not the
  ledger.
- **Defaulting the Bundesland to `BY`**: a silently assumed holiday calendar
  gives wrong sample dates without any sign of it.
- **Base currency as a setting**: it is a `BASE_CURRENCY` constant today;
  making it configurable belongs to `multi-currency-and-fx`.

## Open questions

- Does `init` also upgrade an existing database, or is that a separate
  `migrate` command?
- What does `init` do on a database that already exists: refuse, or report
  and exit successfully?
- Is the Bundesland a flag only, or prompted when `init` runs interactively
  without it?
- Does the out-of-date check run on every command, or only on writes?
- Which settings command shape: one generic `set key value`, or typed setters?
  (Ties into `cli-command-naming`.)
