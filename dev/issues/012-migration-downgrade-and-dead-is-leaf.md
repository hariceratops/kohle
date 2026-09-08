# [fix] The multi-unit migration cannot be downgraded

Found by review on 2026-09-08, over commit `9dcea5b` "Replace transactions
with a multi-unit ledger" — work done before the spec pipeline existed and
never reviewed until now.

## The downgrade fails outright

`alembic/versions/7f3c1d9a2b40_multi_unit_ledger.py:137` rebuilds the old
accounts table with `COALESCE(iban, '')`, because the old schema requires
`iban NOT NULL`. Every account without an IBAN collapses to the same empty
string, against a unique constraint:

```
downgrade INSERT FAILED: UNIQUE constraint failed: accounts_old.iban
```

This is not a corner case. Expense accounts never have an IBAN, virtual
envelopes never have an IBAN, and the README now instructs the reader to
create both. Two such accounts is all it takes, and the migration dies
part-way through.

## The downgrade silently discards child accounts

The same statement filters `WHERE parent_id IS NULL`, so every virtual
sub-account is dropped. The old schema has no parent concept, so there is
genuinely nowhere to put them — but disappearing them without a word is the
wrong way to handle that.

## `Account.is_leaf` is dead code and a trap

`kohle/domain/models.py:123` defines a property used nowhere in the codebase.
It reads `self.children`, the lazy relationship that raises
`DetachedInstanceError` once the unit of work has closed its session — the
exact mistake `dev/design/cli-record-and-balances.md` §7 warns about for tree
rendering, and which `cli.py` carries a comment to avoid. It sits in the model
looking like the obvious way to ask the question.

## Acceptance Criteria

- Downgrading a database containing two or more accounts with no IBAN
  succeeds rather than failing on the unique constraint.
- Downgrading a database containing child accounts does not silently discard
  them: either they are preserved in some form, or the migration refuses to
  run with a message saying what would be lost and why. Silence is the one
  outcome ruled out.
- An upgrade-downgrade-upgrade round trip on a database with expense
  accounts, virtual envelopes and journal entries leaves the ledger readable,
  with the outcome for unrepresentable data stated explicitly rather than
  discovered.
- `Account.is_leaf` is removed, or given a caller and a docstring saying it
  requires an open session.
- A test covers the downgrade path. It has none today, which is why this
  survived: the upgrade was verified by hand against the real database and
  the downgrade only ever ran on data that happened not to trigger it.
