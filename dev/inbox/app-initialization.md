# First-run initialization

## Goal

Give a new user one command that takes kohle from nothing to a usable ledger,
and make every other command say so plainly when that has not happened.

The problem behind it: there is no `init`. On an empty directory
`kohle-cli list-accounts` dies with a raw SQLAlchemy `no such table` error.
The only way to a schema is `alembic upgrade head` from the repo root, which
the README never mentions.

## Considerations surfaced

**Where the database lives.** `kohle.db` is hard-coded relative to the current
directory, in both `kohle/db/connection.py` and `alembic.ini`. Which database
a command touches depends on where it is run. A configurable path (flag,
`KOHLE_DB`, or both) would also decide how plugins and tests find it.

**Migrations ship with the package.** `alembic/` sits outside the `kohle`
package, so an installed `kohle-cli` cannot run migrations outside a checkout.
`init` running them programmatically means packaging them.

**Seed data comes from migrations.** The `People` root is seeded by a
migration; the base `EUR` unit presumably by an earlier one. A fresh database
is only valid after every migration has run in order.

**Mandatory configuration.** `todo.md` lists "mandatory configurations" under
app initialization: values kohle cannot guess (base currency, Bundesland for
`net-worth-history`, see `configurable-net-worth-sampling`). Whether `init`
asks for them is open.

**Not-initialized and out-of-date databases.** Every command opens the
database; a missing schema, or one behind the code's head revision, should
produce one clear message instead of a stack trace. `todo.md` calls this the
"check in top".

## Directions rejected

Creating tables with `create_all` on first connect: it bypasses Alembic and
leaves the revision unrecorded, so later migrations cannot tell where the
database stands.

## Open questions

- Database path: current directory, a fixed per-user location, or
  configurable?
- Does `init` also upgrade an existing database, or is that a separate
  `migrate` command?
- What does `init` do on a database that already exists: nothing, or refuse?
- Does it prompt for configuration or take flags only?
