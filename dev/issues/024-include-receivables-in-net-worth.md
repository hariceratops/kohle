# [feat] Include receivables in net worth

Money owed to the user is worth something, but sitting invisibly in a
person-account balance it doesn't count toward net worth today. This closes
that gap.

Whether receivables are folded into a single net-worth figure or broken out
as a separate subtotal is an open question left to the architect (see
`dev/specs/expense-splitting.md`'s Open Questions) — the spec's only hard
requirement is that they count.

Depends on: 018
Spec: `dev/specs/expense-splitting.md`

## Acceptance Criteria

- Net worth calculation includes person-account (`People` branch, 018)
  balances.
- Whether presented as one folded figure or a separate receivables
  subtotal, the person-account balances are visibly included in the
  reported output, not silently dropped.
- A person account with a negative balance (the user owes them, a
  liability) reduces net worth; a positive balance (they owe the user, a
  receivable) increases it.
