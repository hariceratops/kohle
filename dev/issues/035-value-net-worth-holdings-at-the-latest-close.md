# [feat] Value net-worth holdings at the latest close

`net-worth` reports every holding at cost today. This slice values each
holding at its latest stored close beside the at-cost figure, marking
estimates, so the total covers every holding. It builds the valuation seam
`balance` reuses in 038 and is the first consumer of `latest_close`.

Depends on: none
Spec: `dev/specs/market-value-reporting.md`

## Acceptance Criteria

- Valuation does not live in `kohle/use_cases/journal.py` (the guard in
  `tests/test_price_guards.py` forbids it from touching prices, directly or
  transitively); the design picks the module and how the unit id reaches
  `latest_close`. `_at_cost` and the `NetWorthReport` at-cost properties keep
  their meaning.
- All `latest_close` reads for one report run inside a single `UnitOfWork`
  alongside the balance fold; `today` is passed down from the CLI
  (`date.today()`), never read from a clock inside.
- `net-worth` rows gain `price`, `price date`, `market value` and `status`
  before `at cost`, which stays the last column: `section`, `unit`,
  `quantity`, `price`, `price date`, `market value`, `status`, `at cost`.
  Missing values render `-` via `None`, never a string in a numeric column.
- Per row with nonzero quantity: base currency is quantity × 1 with `-` in
  status, price and price date; a `Fresh` close is quantity × close, status
  `fresh`; a `Stale` close is quantity × close, status `stale (YYYY-MM-DD)`;
  `NoClose` is quantity × average cost, status `no price (at cost)` (never
  fetched, unbound and non-security units are not told apart). The threshold
  is the default 7 days, passed as a parameter; the flag arrives in 037.
- Zero-quantity rows keep their at-cost rendering, get market value 0 and `-`
  for status, price and price date, and no close is looked up for them.
- The existing `Net worth (at cost): X` line stays byte-identical; a
  market-value total line follows it, equal to the sum of all rows' market
  values in both sections. Receivables stay at face.
- A unit held across several accounts is one row, valued with one
  `latest_close` read on the summed quantity.
- Every existing net-worth test passes unchanged, including
  `test_no_price_plugins_means_no_output_change`. The README net-worth
  section's "Every figure is reported at recorded cost" paragraph is
  rewritten and shows the new output; the "no market valuation yet" sentence
  in "Reading the ledger" belongs to `balance` and stays until 038.
