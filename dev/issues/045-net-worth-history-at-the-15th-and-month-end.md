# [feat] `net-worth-history` at the 15th and month-end

A new read-only `net-worth-history` command shows net worth at past sample
dates, each valued by `net-worth`'s rule as of that date.

Depends on: none
Spec: `dev/specs/portfolio-and-profit-reporting.md`

## Acceptance Criteria

- Sample dates: the calendar 15th and the calendar month-end of each month in
  range, plus a final row dated `--to` when `--to` is not itself a sample date.
- `--from YYYY-MM-DD` / `--to YYYY-MM-DD`; default runs from the earliest
  ledger entry to today. A date after today, or `--from` later than `--to`, is
  a usage error. A past `--to` ends with a row dated `--to` and no today row.
- Columns: `date`, `at cost`, `at market`, `estimated` (`K of M`).
- Valuing D: lines dated on or before D (own accounts plus receivables); each
  non-base unit at its last stored close on or before D, never a later one,
  fresh or stale relative to D under `--max-age-days` (default 7); no such
  close means moving-average cost, marked.
- A line dated on a sample date is included; the next day's is excluded.
- With `--to` omitted, the final row matches `net-worth`'s at-cost and
  at-market totals and K, M on the same ledger and today.
- No FIFO runs here, so the lot-shortfall failure does not apply.
- Read-only: row counts unchanged; guard test extended.
- The README documents `net-worth-history`.
- Existing tests pass unchanged.
