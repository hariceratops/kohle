# [feat] Capture counterparty on imported entries

The spec's rule engine matches on description and counterparty, but
counterparty does not survive an import today. `ImportStatement`'s schema
requires an `iban` column, validates it, and then discards it; the Deutsche
Bank importer renames `Beneficiary / Originator` to `beneficiary` and drops
the column before `ImportStatement` ever sees it. Neither field has anywhere
to live — `JournalEntry` has no counterparty column at all.

Nothing downstream can match on a payee until this lands.

Spec: `dev/specs/expense-classification.md`

## Acceptance Criteria

- `JournalEntry` gains nullable `counterparty_name` and `counterparty_iban`
  columns, added by an Alembic migration.
- The columns are `None` for entries made through `record` and
  `record-split`, which have no counterparty concept. Nullable is the
  honest representation; no placeholder value is invented.
- `ImportStatement` populates both columns from the imported dataframe
  instead of validating `iban` and throwing it away.
- The importer plugin contract expects a plugin to supply both a
  counterparty name and an IBAN column. State how a plugin that cannot
  supply one is expected to behave — omission must not be silent, given a
  missing counterparty is what makes a rule stop matching later.
- The Deutsche Bank importer keeps `beneficiary` rather than dropping it,
  and its output satisfies the extended contract.
- Counterparty is visible on at least one read command, so the data can be
  confirmed present without opening the database.
- Existing imports still work: a statement that imported cleanly before
  imports cleanly after, and the reference hash is unchanged so previously
  imported rows are still recognised as duplicates.
- The migration downgrades, per the standard set by issue 012: either the
  columns are dropped cleanly, or the downgrade refuses and names what would
  be lost.
