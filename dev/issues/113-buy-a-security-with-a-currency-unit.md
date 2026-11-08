# [feat] Buy a security with a currency unit, cost from its lots

A purchase paid in INR consumes that account's INR lots FIFO, and the stock lot's euro cost is the euros those lots cost; the purchase realises nothing.

Depends on: 111

Implement after 120, so `net-worth` is already correct for opening entries.

## Acceptance Criteria

- The stock lot's euro cost is the summed euro cost of the INR consumed, not the line's own `unit_price`.
- Remit 1,000 EUR for 90,000 INR, then 1,100 EUR for 100,000 INR, then buy shares for 120,000 INR: the stock lot costs 1,330.00 EUR and the remaining INR lot is 70,000 INR at 770.00 EUR.
- The purchase realises no gain.
- How a line with no euro figure on its face is stored and balanced follows `dev/design/multi-currency-and-fx.md`.
- The moving-average fold behind `balance` and `net-worth` reads the same euro costs.
- `recording-entries.md` is updated.
- The per-entry replay, balancing per price currency, the costs in the moving-average fold and the module moves (`balance_sheet_accounts` into `accounts.py`, `BASE_CURRENCY` into `domain/models.py`, re-exported from `journal.py`) land here.
