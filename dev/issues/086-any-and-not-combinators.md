# [feat] `any` (OR) and `not` (NOT) combinators

Let conditions combine with OR and NOT, nested, so one rule can express what would otherwise take several.

Depends on: 084, 085
Spec: `dev/specs/complex-classification-rules.md`

## Acceptance Criteria

- `any = [ {...}, {...} ]` holds when any item holds; each item is an AND of its own keys.
- `not = {...}` holds when its contents do not; `any` and `not` nest inside each other.
- An empty `any` or an empty `not` is rejected with the rule position and key named, and nothing is written.
- `not` over a counterparty or IBAN condition holds for a line with no counterparty.
- Evaluation stops as soon as an AND or an OR is decided, and `match_rule` stays pure.
- `show-rules` renders nested rules with each OR alternative on one line, and `apply-rules --yes` on that output reports no changes.
- The `Groceries` example in the spec classifies a line containing `rewe`, and a line for `edeka` without `pfand`, but not an `edeka` line containing `pfand`.
