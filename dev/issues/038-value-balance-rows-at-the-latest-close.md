# [feat] Value balance rows at the latest close

`balance` shows a per-unit holding and what was paid for it. It gains market
value from the valuation seam built in 035, with the same markers, summary and
threshold flag as `net-worth`.

Depends on: 035, 036, 037
Spec: `dev/specs/market-value-reporting.md`

## Acceptance Criteria

- `balance` rows are `unit`, `quantity`, `price`, `price date`,
  `market value`, `status`, `average cost`: the new columns go before
  `average cost`, which stays last, and existing values are unchanged.
- The same valuation rules and status words as `net-worth` apply, from the
  same function; no second copy of the rule.
- Two lines end the output: a market-value total equal to the sum of the rows'
  market values, then the `K of M holdings estimated (S stale, C at cost)`
  summary. `balance` prints no at-cost total.
- `balance --max-age-days N` behaves as on `net-worth`.
- The `Total (base currency)` restatement row renders `-` in the new columns
  except market value, which is the quantity; no `str` enters a numeric column
  (the `floatfmt`/`missingval` trap documented in `balance_cmd`).
- `No holdings` output is unchanged and gets neither new line.
- `test_balance_renders_none_average_cost_as_dash_without_breaking_other_rows`
  and every other existing `balance` test pass unchanged.
- The README "Reading the ledger" section drops "no market valuation yet" and
  shows the new output.
