# [feat] Roll balances up an account subtree

A parent account's balance is defined as the sum of its children, and parent
accounts are never posted to directly. Extend `balance` to aggregate across
an account's whole subtree so a parent reports something meaningful.

Depends on: 002
Spec: `dev/specs/cli-record-and-balances.md`

## Acceptance Criteria

- `balance` on a parent account aggregates journal lines from every
  descendant account, grouped by unit.
- Recursion handles arbitrary depth, not only immediate children.
- `balance` on a leaf account behaves exactly as it did after 002.
- A new recursive-descendant query against `Account.parent_id` is added;
  `account_lines_service` fetches only one account's own lines and is
  insufficient here.
- The spec's cash-envelope scenario runs end to end: `balance Cash` totals
  across `Unallocated`, `Groceries` and `Eating out`, and `balance Groceries`
  reports that envelope alone.
- An envelope spent past zero reports a negative balance and is not treated
  as an error condition — a negative balance is the overspend signal.
