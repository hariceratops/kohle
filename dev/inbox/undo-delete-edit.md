# Undo, delete and edit

## Goal

Settle, before the infrastructure is wired further, how kohle undoes, deletes
and edits what it has recorded, and what role the audit trail plays in that.

The problem behind it: a few corrections already exist (`reclassify`,
`unsplit-line`, `remove-rule`), each built for its slice. There is no general
stance on undo, and the question was raised whether the audit trail written by
the CRUD infrastructure could drive undo generically.

## Considerations surfaced

**What the audit trail records today.** `kohle/infrastructure/crud.py` wraps
writes and records an `Operation` per successful create, update or delete:
entity type, entity id and action, grouped by `OperationGroup`. The
`Operation` model has `field` and `state` columns, but nothing fills them. An
update is recorded as having happened, without the value it replaced.

**Why the audit trail cannot drive undo.** Without before-images an update
cannot be reverted. Even with them, a generic "revert this row" contradicts
the ledger: the journal is append-only, and rewriting or deleting a recorded
line changes history that reports, FIFO lots and classification records
already depend on.

**Proposed direction: undo is a domain compensation.** kohle already undoes
things the accounting way:

- `reclassify` posts a reversing-and-re-posting adjusting entry;
- `unsplit-line` reverses a split, leaving the original and the split entries
  in place;
- rules and accounts are retired with `deleted_at` (soft delete), and the
  audit trail records that as a delete.

Undo, delete and edit stay domain operations that append a correction. The
audit trail stays what it is: a record of what happened, read by
`list-operations`.

**A single "undo last" verb is possible on top.** It would be a dispatcher:
read the most recent operation group, recognise which domain operation it was,
and call that operation's compensation — not a row revert. Whether it is worth
having is open.

**Imports.** Re-importing is already idempotent (deduplication by native
reference per account). Undoing a whole import would be a compensation over
every entry the import created, which the operation group identifies.

**Edits are retire-and-replace where identity matters.** The rule-editor
direction in `complex-classification-rules` already works this way: an
unchanged rule keeps its id; a changed one is retired and replaced, so
records pointing at the old id stay true. The same pattern applies wherever
recorded data refers to the thing being edited.

**Sync constraint.** Corrections are writes, so they happen on the single
writer device (see `device-topology-and-sync`).

## Directions rejected

- **Generic undo from the audit trail**: it lacks before-images, and a row
  revert contradicts the append-only ledger.
- **Hard deletes of recorded ledger data**: history that reports and lots
  depend on would silently change.

## Open questions

- Is a generic "undo last operation group" verb wanted, or only per-operation
  corrections?
- Should `field` and `state` on `Operation` be filled (for a fuller audit
  record), or dropped as unused?
- Which operations still have no correction at all (for example, an entry
  recorded by hand with a wrong amount or date), and what does each one's
  compensation look like?
- Is undoing a whole import needed, or is reclassifying and adjusting enough?
