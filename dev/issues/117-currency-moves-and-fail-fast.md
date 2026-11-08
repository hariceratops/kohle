# [feat] Currency moves between own accounts, and fail-fast rules

INR moved between own accounts carries its lots, and the cases that cannot be valued fail with a named error.

Depends on: 111

## Acceptance Criteria

- A move between own accounts keeps each lot's date and cost and realises nothing.
- Spending more of a currency unit than an account's lots hold is a lot shortfall naming the unit, the account, the date and the shortfall.
- A currency unit moving between an own account and a People account, either direction, is refused with an error naming the entry.
- `positions`, `realised`, and `balance`/`net-worth` where their euro cost depends on lots fail as a whole on these errors.
- `accounts-and-units.md` is updated.
