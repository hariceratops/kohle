# [feat] An incoming remittance rule and its completion

A remittance rule may match a euro inflow (rupees changed back), with the same pending-then-complete shape, completing to the reverse two-amount entry of issue 115. Depends on 133.

## Acceptance Criteria

- A remittance rule matches in the incoming direction, restricted by the existing `direction` condition when the user wants one direction only.
- Pending, incoming: the euros received are offset by the pending bucket, and the unit stays on the counterpart until completion; nothing is counted twice.
- The classification record holds the counterpart, the unit and the direction.
- The completing command from 133 takes Y of the unit out of the counterpart, consuming lots FIFO, and clears X EUR from the pending bucket, dated at the original line.
- With IndianBank holding one 90,000 INR lot costing 1,012.00 EUR, a 1,100.00 EUR inflow completed with Y = 90,000 INR consumes that lot and shows 88.00 EUR realised gain under unit `INR` in `realised`; nothing remains pending.
- A shortfall of lots fails as `multi-currency-and-fx` requires and writes nothing.
- Pending remittances are listed in both directions.
- Recording never reads a fetched price or rate; `tests/test_price_guards.py` holds.
- `recording-entries.md` and `import-and-classification.md` are updated with a fictional euro inflow.
- Every existing test passes unchanged.
