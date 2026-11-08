# [feat] `net-worth-history` values each date at the close and rate on or before it

History applies the same valuation rule as `net-worth` as of each sample date.

Depends on: 120

## Acceptance Criteria

- Each sample date uses the latest close and the latest rate on or before it.
- A date with no close or rate falls back to cost and is marked, as in 120.
- `reports.md` is updated.
