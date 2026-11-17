# [feat] Complete an outgoing remittance with Y

A completing command takes the entry id and the currency received, and turns the pending line into the two-amount entry of `multi-currency-and-fx`. Depends on 132.

## Acceptance Criteria

- The completing command takes the entry id and Y, and posts an adjusting two-amount entry dated at the original line, as `reclassify` dates its reversing pair.
- It takes X EUR out of the pending bucket and puts Y of the unit into the counterpart; the rate is derived as X / Y and never typed.
- A 1,012.00 EUR card payment with Y = 90,000 INR gives one INR lot on IndianBank costing exactly 1,012.00 EUR, and nothing for it remains in a pending state or an unclassified bucket.
- FIFO sees the lot on the day the euros left, including when other entries are recorded out of order.
- The command is `complete-remittance ENTRY_ID AMOUNT`.
- The classification record shows the remittance completed.
- `reclassify` and `split-line` refuse a completed remittance (`uncomplete-remittance` first).
- The command is shaped so a later Indian bank importer can call it when its currency row is the remittance's mirror.
- Completion is all-or-nothing and one audit-trail group; completing an already-completed or non-remittance entry fails and writes nothing.
- Recording never reads a fetched price or rate; `tests/test_price_guards.py` holds.
- `recording-entries.md` and `import-and-classification.md` are updated.
- Every existing test passes unchanged.
