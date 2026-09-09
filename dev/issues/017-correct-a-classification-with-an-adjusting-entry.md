# [feat] Correct a classification with an adjusting entry

A rule will sometimes pick the wrong account, and a fall-through row needs a
home. Correcting either means posting an adjusting entry — never editing the
original line.

That is forced by the codebase, not chosen: `cli-record-and-balances`
already established append-only correction by reversing entry for this same
model, and there is no update path to use even if one were wanted —
`crud_create` hardcodes `action="create"`, there is no `crud_update`, and
nothing writes `Operation.field` or `Operation.state`. A `reclassify` that
rewrote history would be inventing an update mechanism this codebase
deliberately does not have.

Depends on: 015
Spec: `dev/specs/expense-classification.md`

## Acceptance Criteria

- A CLI command moves a classified line to a different expense or income
  account by posting a reversing pair through `post_entry`: the wrong
  account is credited and the right one debited, for the original amount.
- The original entry is never edited, voided or deleted.
- The line's classification record is updated: the final account becomes the
  corrected account, and the corrected flag is set. The proposed account and
  the rule that matched are left as they were — they are the record of what
  the engine got wrong, which is the whole point of capturing them.
- Correcting a line that fell through to an unclassified bucket works the
  same way as correcting a wrong rule match.
- How a line is identified — by entry reference, by id, or otherwise — is
  whatever the design settles on. The constraint this issue is accepted
  against is that the identifier is discoverable from what 016 already
  prints.
- An unknown line or an unknown target account produces a clear error, not a
  traceback.
- Posting to a non-leaf account fails with the existing leaf-only rule,
  surfaced readably.
- Balances reflect the correction: after reclassifying, `balance` on the
  wrong account no longer includes the amount and `balance` on the right one
  does.
