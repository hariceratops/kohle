# [feat] `every N days|weeks|months from A` and `yearly MM-DD` recurrence kinds

Build the two kinds `configurable-net-worth-sampling` assigns to `budgeting`, in the shared recurrence vocabulary, and let `set-sampling-rules` accept them.

Depends on: none
Spec: `dev/specs/budgeting.md`

## Acceptance Criteria

- `every N days|weeks|months from A` parses, renders and yields occurrences in both directions from A; A fixes only the phase (`every 3 months from 2026-01-15` also lands on 2025-10-15).
- A month-based occurrence keeps A's day clamped to each month's length without drifting: `every 1 months from 2026-01-31` lands on 01-31, 02-28, 03-31.
- `yearly MM-DD` yields that calendar day every year; `yearly 02-29` lands on 02-28 in non-leap years.
- Neither kind shifts to a working day; the five existing kinds keep their shift.
- There is no `years` unit; `every 2 years from …` is refused with an error naming the valid units.
- `set-sampling-rules` accepts both kinds (for example `salary: every 2 weeks from 2026-01-02`) and `net-worth-history` samples on them.
- `net-worth-history` output is unchanged for existing rule lists; existing tests pass.
