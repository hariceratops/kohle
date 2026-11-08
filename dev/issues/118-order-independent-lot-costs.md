# [test] Lot-derived costs are independent of insertion order

Recording an entry dated earlier than existing ones must give exactly what a full replay in `(entry_date, line id)` order gives.

Depends on: 113, 115, 116, 117

## Acceptance Criteria

- The same entries recorded in two different insertion orders give identical `positions`, `realised`, `balance` and `net-worth` output.
- The test includes a remittance, a purchase, a reconversion and a rated inflow, with at least one backdated entry.
- Any defect found is fixed in this slice or recorded as an issue.
- Entries that touch the same lots are on distinct dates; same-date entries are ordered by insertion and are out of scope for the order-independence claim.
