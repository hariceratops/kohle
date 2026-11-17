# [test] Cross-cutting guards for transfers and remittances

Closes the spec's feature-wide guarantees that no single slice owns. Depends on 126 to 135.

## Acceptance Criteria

- A ledger whose rules have no transfer or remittance action gives exactly today's output from every command; existing rules naming an asset account such as `Transfers` keep their meaning.
- `tests/test_price_guards.py` holds for every new path: no transfer, remittance or completion takes a euro figure from `prices`.
- Every writing command (import, `classify-rules`, corrections, join, completion, reversal) is all-or-nothing: a crash part-way leaves the ledger untouched and no audit-trail group.
- The classification records tell apart a rule-made transfer, an absorbed mirror, a pending remittance, a completed remittance in either direction, and a human correction.
- The docs examples (Savings mirror statement, remittance card payment, reverse inflow) run as checked `console` blocks with fictional accounts, counterparts, IBANs and amounts.
- Every existing test passes unchanged.
