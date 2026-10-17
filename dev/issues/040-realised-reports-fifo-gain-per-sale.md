# [feat] `realised` reports FIFO gain per sale

A new read-only `realised` command replays a depot's lines in ledger order and
lists each sale with the gain computed against the oldest lots first. Figures
are gross (before fees and tax), a cross-check against the broker.

Depends on: none
Spec: `dev/specs/portfolio-and-profit-reporting.md`

## Acceptance Criteria

- `realised` prints one row per sale with columns `date`, `account`, `unit`,
  `quantity`, `proceeds`, `FIFO cost`, `gain`; proceeds are the quantity sold
  × the sale line's recorded unit price.
- A buy-buy-sell sequence in one depot gives the FIFO gain, consuming the
  oldest lot first.
- A `Realised gain: X` total line closes the output; totals are summed as
  exact `Decimal`s, money is `.2f`, missing cells are `-`.
- `--year YYYY` lists only sales dated in that year; their gains still use lots
  bought in earlier years (the replay always covers the full history). Without
  `--year`, every sale from all years is listed under one total.
- The People subtree is excluded.
- The command writes nothing: `prices`, `operations` and `operation_groups`
  row counts are unchanged, and its code references no price writer or plugin
  loader (`tests/test_price_guards.py` extended).
- Every existing test passes unchanged.
- The README documents `realised` and states that `balance`'s `average cost` is
  a moving average while `realised` uses FIFO.
