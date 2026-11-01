# [feat] Unclassified and uncapped rows in `budget`

Make sure spending without a cap cannot hide.

Depends on: 079
Spec: `dev/specs/budgeting.md`

## Acceptance Criteria

- One row shows `Unclassified Expense` spending over the whole `--from`/`--to` range; a line there appears only in that row.
- One "uncapped" row shows spending over the whole range on lines whose account had no cap in force, on itself or any ancestor, on the line's date; it leaves out `Unclassified Expense`.
- A line on a child of a capped parent is covered and absent from the uncapped row.
- A line dated D or later on an account whose cap was ended from D lands in the uncapped row.
- `net-worth-history` output is unchanged by this feature.
