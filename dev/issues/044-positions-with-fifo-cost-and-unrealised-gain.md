# [feat] `positions` with FIFO cost and unrealised gain

A new read-only `positions` command shows each held security across all own
accounts, valued at its latest stored close, with the FIFO cost of the lots
still held and the unrealised gain.

Depends on: 042, 043
Spec: `dev/specs/portfolio-and-profit-reporting.md`

## Acceptance Criteria

- One row per security with nonzero quantity, summed across own accounts
  (`net-worth`'s own-accounts partition, People subtree excluded).
- Columns: `unit`, `quantity`, `price`, `price date`, `market value`, `status`,
  `FIFO cost`, `unrealised gain`; status words are `net-worth`'s (`fresh`,
  `stale (YYYY-MM-DD)`, `no price (at cost)`).
- `FIFO cost` is the cost of the lots still held, summed over depots;
  `unrealised gain` is `market value − FIFO cost`. A no-close row falls back to
  its FIFO cost, so its gain is 0, and it is marked.
- Three total lines (market value, FIFO cost, unrealised gain) follow the
  table, then the `K of M holdings estimated (...)` line, via the shared
  helpers; totals equal the sums of the rows.
- `--max-age-days N` (default 7) behaves as on `net-worth`.
- A lot shortfall, or a People-account security move, fails as in 041 and 043.
- Row and valuation shape assume `kind == security` only in the row-selecting
  filter, so other non-base units can be added later without redesign.
- Read-only: row counts unchanged; code references no price writer or plugin
  loader (`tests/test_price_guards.py` extended).
- The README documents `positions`.
- Existing tests pass unchanged.
