# [feat] All seven recurrence kinds as period boundaries in `budget`

Let a cap use any kind of the shared vocabulary, including the two built in 074.

Depends on: 074, 076
Spec: `dev/specs/budgeting.md`

## Acceptance Criteria

- `set-cap` and `budget` accept `workday N`, `<nth> <weekday>`, `last workday`, `last day`, `every N days|weeks|months from A` and `yearly MM-DD`.
- `workday 25` yields payday-to-payday periods under the Bundesland in force at each date.
- The shifting kinds, with no Bundesland entry, refuse and point to `move-state --from start <code>`, as `net-worth-history` does.
- `every 1 months from 2026-01-31` yields periods 01-31–02-27, 02-28–03-30, 03-31–04-29; `yearly 02-29` yields a boundary on 2027-02-28.
- `every`/`yearly` periods never shift to a working day.
