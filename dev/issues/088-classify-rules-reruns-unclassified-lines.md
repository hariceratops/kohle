# [feat] `classify-rules` re-runs the rules over unclassified lines

Let the user apply a changed rule set to lines that were left unclassified, only when they ask for it.

Depends on: 082
Spec: `dev/specs/complex-classification-rules.md`

## Acceptance Criteria

- `classify-rules` runs the current rule set over lines in `Unclassified Expense` or `Unclassified Income` and previews each line that would move: date, description, amount, current bucket, target account, matched rule.
- It asks before applying; `--yes` skips the question.
- Each move is posted as a correcting entry, the same way `reclassify` does.
- The recorded `Classification` for a move distinguishes it from a human correction and records the rule that matched; the stored shape is for the architect to decide.
- Lines a rule already classified or a human reclassified are never touched.
- Changing rules with `edit-rules`, `apply-rules` or `add-rule` never reclassifies anything.
- It is all-or-nothing and recorded as one audit-trail group; a declined prompt or a crash part-way leaves the ledger untouched.
- A reader device refuses `classify-rules`.
