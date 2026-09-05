# [feat] Show accounts as a tree in `list-accounts`

`Account` gained a parent/child relationship in the ledger rework, but
`list_accounts_cmd` still prints a flat list with a raw numeric `parent=1`.
The cash-envelope workflow depends on getting the account tree right, and
verifying it is currently a matter of matching ids by eye.

Independent of the other issues.

## Acceptance Criteria

- `kohle-cli list-accounts` renders the account hierarchy as a tree — nesting
  shown structurally (indentation or similar), not as a numeric parent id.
- A parent is visibly distinguishable from a leaf, since only leaves can be
  posted to.
- Accounts with no parent appear at the top level.
- Arbitrary nesting depth renders correctly, not only one level.
- Account type and IBAN remain visible for each account.
- `list-child-accounts` continues to work unchanged, or is folded into this
  command if the tree view makes it redundant — state which in the
  implementation.
