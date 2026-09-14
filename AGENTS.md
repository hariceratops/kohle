# Project: kohle

## Context

Kohle is a personal money manager for the command line, written in Python
3.12 and installed as a `uv` project. It keeps a double-entry ledger in
SQLite through SQLAlchemy 2.0, with Alembic managing the schema. Bank
statements arrive through importer plugins discovered from the
`kohle.plugins` entry-point group. `kohle-cli` is the primary frontend;
`kohle-tui` is a Textual application intended as a second frontend over the
same use cases, and is currently unwired.

The ledger is multi-unit: every journal line carries a quantity, the unit it
is denominated in, and the price that unit had at the time of the
transaction. Cash in the base currency is stored at price 1, so cash lines
and asset lines have the same shape and reporting never branches on which
kind it is. Prices fetched later live in their own table and are read only by
reporting, never by transaction recording — a recorded entry must not depend
on what a price source said on any particular day.

Accounts form a tree and everything is an account: bank accounts, virtual
sub-accounts for earmarked savings, instruments, expense categories, and
people (their own `People` branch, holding what they owe or are owed). A
parent account's balance is the sum of its children, so only leaf accounts
may be posted to. Account names are globally unique because lookup is by
bare name; scoping a name to its parent needs qualified paths, which do not
exist yet.

Code is layered `app` → `use_cases` → `services` → `infrastructure` /
`domain`. Use cases validate and compose; services own persistence and are
the only layer that touches a `Session`. A use case runs inside a
`UnitOfWork` that wraps one database transaction and records an audit trail
of `Operation` rows through the `crud_create` decorator. The `OperationGroup`
holding them is created on the first recorded write, so a use case that only
reads leaves no trace and group ids run consecutively across writes.
Functions return
`Result[T, E]` rather than raising; domain errors are `Exception` subclasses
used as error values and are not thrown.

## Overrides

Broad exception catching at transaction boundaries: `DbTransactionContext.run`
and `DbTransaction.execute` catch `Exception` rather than an explicit list of
types. This replaces the general rule that exceptions should be caught by
explicit type. The justification is that these two functions are the seam
where the codebase converts arbitrary failure into a `Result` and rolls the
transaction back — an unanticipated exception escaping there would commit or
leak a half-written ledger entry, which is the one outcome the design exists
to prevent. Ruff reports these as `BLE001`; they are deliberate. Anywhere
else, catch explicit types.
