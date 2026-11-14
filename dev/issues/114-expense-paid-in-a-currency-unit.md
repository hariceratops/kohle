# [feat] An expense paid in a currency unit is valued at lot cost

Spending INR on an expense takes its euro amount from the INR lots consumed, with no gain realised.

Depends on: 111

## Acceptance Criteria

- The INR consumed FIFO gives the expense its euro amount.
- No gain appears in `realised`.
- Reports that show expenses use the lot-derived euro amount.
- `recording-entries.md` is updated.
