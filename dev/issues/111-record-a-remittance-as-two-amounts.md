# [feat] Record a remittance as two amounts

`record` accepts euros taken from a euro account and a currency unit put into an own account, deriving the rate and creating a lot of that unit at the euros actually sent.

## Acceptance Criteria

- The entry takes `X EUR` from a euro account and puts `Y` of a non-base currency unit into an own account; the rate is derived as X / Y and is never typed.
- The lots replay covers non-base currency units, not only securities; no code names INR.
- Remitting 1,000 EUR for 90,000 INR creates one INR lot whose cost is exactly 1,000.00 EUR; the transfer fee is part of X.
- `balance` shows the INR quantity on the account.
- Recording never reads a fetched price or rate; `tests/test_price_guards.py` still holds.
- `recording-entries.md` and `accounts-and-units.md` are updated.
- Every existing test passes unchanged.
- Lot costs are exact fractions, so a lot of 90,000 INR for 1,000 EUR costs exactly 1,000.
- From this slice until 121, INR shows as a `positions` row with its price printed at 2 decimals.
