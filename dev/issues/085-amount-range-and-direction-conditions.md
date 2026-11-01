# [feat] Amount range and direction conditions

Let a rule tell a monthly 500 from a one-off 2000 to the same IBAN, which is the case this feature exists for.

Depends on: 084
Spec: `dev/specs/complex-classification-rules.md`

## Acceptance Criteria

- `amount = { min = M, max = N }` tests the absolute amount, includes both ends, and either end may be left open; amounts are compared as exact decimals, never floats.
- `direction = "in"` or `"out"` is a separate condition on the line's sign; `match_rule` receives the line's signed amount.
- A range whose low end is above its high end is rejected with the rule position and key named, and nothing is written.
- Two rules on the same IBAN, one with `amount = { min = 400, max = 600 }` and one with `{ min = 1500 }`, send a 500 and a 2000 outgoing payment from one statement to two different accounts.
- A line with no counterparty name or IBAN fails any counterparty or IBAN condition.
- `show-rules` renders these conditions and `apply-rules --yes` on that output reports no changes.
