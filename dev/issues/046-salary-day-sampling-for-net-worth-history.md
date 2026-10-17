# [feat] Salary-day sampling for `net-worth-history`

The month's period-end sample becomes the salary credit date, the last working
day of the month, with the working-day rule exposed per Bundesland.

Depends on: 045
Spec: `dev/specs/portfolio-and-profit-reporting.md`

## Acceptance Criteria

- `--period-end month-end|last-working-day`, default `last-working-day`;
  `month-end` keeps the calendar last day. The 15th never moves.
- Working day: Monday to Friday, excluding the state's public holidays (from
  the `holidays` package, a new dependency pinned in `pyproject.toml`) and
  excluding 24 and 31 December. The rule sits behind one small predicate.
- `--state XX` (default `BY`); an unknown code is a usage error before
  anything is read; no effect with `--period-end month-end`.
- A month whose last day is a Saturday or a Bavarian holiday samples the
  preceding working day.
- December's period end is 30 December when a weekday, otherwise the preceding
  working day (2028: Friday 29 December); 24 and 31 December are never sample
  dates.
- The row is dated the salary day and includes that day's lines.
- The README documents both flags.
- Existing tests pass unchanged.
