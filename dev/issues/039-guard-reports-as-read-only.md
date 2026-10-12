# [test] Guard reports as read-only

Reports are a pure read of stored history; fetching from a report was
rejected because it would make the same ledger report differently on
different days. A test should fail if that is ever reversed.

Depends on: 035, 038 (lands last: its `balance` half means nothing until 038)
Spec: `dev/specs/market-value-reporting.md`

## Acceptance Criteria

- Running `balance` and `net-worth` leaves the `prices` row count unchanged
  and writes no `Operation` row.
- The CLI callbacks of both commands reference none of `load_price_plugins`,
  `PriceFetcherPlugin`, `call_price_plugins`, `AppendPrices` or
  `add_price_service`, checked on exact identifiers as in
  `tests/test_price_guards.py`. The same check covers the source of
  `kohle/use_cases/reporting.py`, where a price writer would realistically be
  added (design: `dev/design/market-value-reporting.md`).
