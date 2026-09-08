# [feat] Show average cost per unit in `balance`

Without a price feed there is no market value to report, so the only value
information available is what was paid. Add weighted-average cost per unit to
the balance report, computed from the `unit_price` already recorded on each
journal line.

Depends on: 002 (and on 004 to be observable for a non-base unit)
Spec: `dev/specs/cli-record-and-balances.md`

## Acceptance Criteria

- Each unit row in `balance` shows an average cost, weighted by quantity,
  computed from the `unit_price` on the contributing lines.
- The figure is explicitly average cost, not FIFO lot cost — FIFO belongs to
  `dev/inbox/portfolio-and-profit-reporting.md` and is out of scope here.
- Holdings in the base currency show an average cost of 1.
- After the spec's ETF purchase, `balance Broker` shows one row reading
  10 units of `IE00B4L5Y983` at average cost 100.
- No market value or valuation total is shown anywhere — there is no price
  source to compute one from.
