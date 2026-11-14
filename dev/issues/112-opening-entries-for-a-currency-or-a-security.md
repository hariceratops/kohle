# [feat] Opening entries for a currency or a security

Existing holdings enter as an opening entry with a quantity and a stated total euro cost from a named opening account, instead of a backdated history.

Depends on: 111

## Acceptance Criteria

- `record` takes a quantity and a total euro cost against an opening account the user names; the lot's cost is the stated euro amount.
- It is the two-amount form of 111 with a different source account, not a second mechanism.
- It works for a currency unit and for a security.
- `recording-entries.md` documents opening balances.

## Review 2026-11-11
- The test checks that the lot's cost equals the stated total, but not that `net-worth` rises by the opening amount, which is why the docs recommend an `income` opening account.
