# [feat] Cap changes cut at the effective date

A new cap entry ends the running period and starts a new one, so there are no gaps or overlaps.

Depends on: 076
Spec: `dev/specs/budgeting.md`

## Acceptance Criteria

- An entry taking effect at D ends the running period on D−1 and starts a new period at D that ends the day before the new recurrence's next occurrence after D.
- A cap's first period starts at its D: `every 3 months from 2026-01-15` set from 2026-01-01 gives 01-01–01-14 (short) then 01-15–04-14.
- With 300 from 2026-01-01 on `day 1`, adding `set-cap … 400 "day 1" --from 2026-03-10` gives March periods 03-01–03-09 (short, cap 300) and 03-10–03-31 (short, cap 400), and April full at 400.
- Periods cut short are marked short; the cap is not prorated.
- Repeating an existing D for the account replaces that entry; the replacement is one `Operation`.
- A future D is accepted and shows in `list-caps` but not in `budget` until it starts.
- An entry identical (same amount and rule) to the one in force before it does not cut the period, so fixing a wrong date does not double the cap. This is a user-approved refinement of the spec's cut-at-D wording (design §4.1); the spec text is still to be revised.
