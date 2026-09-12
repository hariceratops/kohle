# [feat] Undo or edit a recorded split

A split will sometimes be wrong — the wrong person, the wrong share — and
correcting it needs the same mechanism as correcting a classification: a
further adjusting entry against the same lines, not an in-place rewrite.
Inventing a separate undo path for splits would duplicate what `reclassify`
already does.

Depends on: 019
Spec: `dev/specs/expense-splitting.md`

## Acceptance Criteria

- A CLI command undoes or edits a previously-recorded split (019) by
  posting a further adjusting entry against the same lines.
- The original split's `Operation` rows remain intact and traceable — no
  `Operation` or line is mutated in place.
- After undoing a split, the expense account and person account balances
  return to what they were before the split (own account back to the full
  original amount, person account back to zero for that line).
- After editing a split to different shares, both accounts reflect the new
  shares, and the full history (original import, first split, correction)
  remains readable via `Operation` rows.
- An unknown split reference produces a clear error, not a traceback.
