# [feat] Per-currency subtotals in `net-worth` and `positions`

Both reports show a subtotal per currency next to the euro totals.

Depends on: 120, 121

## Acceptance Criteria

- Each subtotal gives the market value in that currency and in euros.
- A holding's currency is the unit itself for a currency unit, its binding's quote currency for a bound security, and EUR for an unbound security.
- The native-currency figure is `-` when any member of the subtotal has no close in that currency.
- The euro total is unchanged and still equals the sum of the rows.
- `net-worth-history` and `balance` get no subtotals.
- `reports.md` is updated.
