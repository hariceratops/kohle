# [feat] Summarise estimated holdings in net-worth

A market total that quietly mixes real prices with estimates is easy to
misread, so the report says how many holdings are estimated and why.

Depends on: 035
Spec: `dev/specs/market-value-reporting.md`

## Acceptance Criteria

- After the market total, `net-worth` prints
  `K of M holdings estimated (S stale, C at cost)`.
- M is the number of non-base-currency rows with nonzero quantity; K = S + C;
  base-currency and zero-quantity rows are not counted.
- When K = 0 the line still prints, as `0 of M holdings estimated`, so the
  output shape does not depend on the data.
- Tested on a ledger mixing base-currency, fresh, stale, no-close and
  zero-quantity rows, with K, S, C and M all asserted.
