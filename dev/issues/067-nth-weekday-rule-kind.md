# [feat] nth-weekday rule kind

Add `<nth> <weekday>` (`1st`–`4th`, `mon`–`sun`), e.g. `3rd fri`, for salaries
paid on a weekday pattern.

Depends on: 066
Spec: `dev/specs/configurable-net-worth-sampling.md`

## Acceptance Criteria

- `3rd fri` yields the third Friday of each month (always days 15–21); if that
  day is not a working day, the previous working day.
- Ordinals `5th` and `last fri` are rejected with an error that lists the
  valid choices.
- A shift can land in the previous month (`1st fri` on 1 May becomes 30 April)
  and the row is dated where it lands.
- `mid-month: day 15; salary: 3rd fri` in a month whose third Friday is the
  15th yields one row with both roles.
- Existing tests pass.
