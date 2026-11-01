# [feat] `budget` report for a capped account

Show, per period, how actual spending compares with the cap. This slice covers `day N` periods; other kinds follow in 077.

Depends on: 075
Spec: `dev/specs/budgeting.md`

## Acceptance Criteria

- `budget --from D --to D`; defaults are `--to` today and `--from` 1 January of `--to`'s year.
- A cap of 300 with `day 1` from 2026-01-01 yields January, February, and so on; each period runs from one occurrence to the day before the next.
- Spending is net (debits minus credits) on the capped account and its subtree for lines dated within the period; 100 spent and 30 refunded shows 70; a period can be negative. Lines count at their recorded value.
- A line on a child of a capped parent counts toward the parent's cap; parent and child caps are checked independently.
- Every period overlapping the range is shown whole, not clipped; periods starting after today are not shown.
- Columns: account, period start and end, cap, spent, signed over/under (positive means overshoot); over-cap rows are marked.
- The period containing today is marked partial and shows `day N of M`, counting today.
- No rollover: each period stands alone.
- `budget` leaves the `operations` and `operation_groups` row counts unchanged and calls no price plugin.
