# [feat] Value holdings quoted in another currency

`net-worth` and `balance` value an INR-quoted stock as quantity × close × rate, and INR cash as quantity × rate.

Depends on: 107, 111

Implement before 113.

## Acceptance Criteria

- Market value in euros = quantity × latest close (in its quote currency) × latest rate of that currency, each the latest on or before the date; their dates need not match.
- The status is the worse of the two; a stale status shows the older date.
- If the close or the rate is missing, the holding falls back to its euro cost and is marked `no price (at cost)`.
- INR cash is valued at quantity × rate under the same rules.
- `value_balances` stays the single place a close is read.
- `reports.md` is updated.
