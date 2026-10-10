# [feat] Introduce the People account branch

People accounts need somewhere to live before anything can post to them.
Splitting an imported line, undoing a split, grouping splits, and folding
receivables into net worth all assume a person account already exists — this
issue is what makes that assumption true.

A person is an account, not a parallel subsystem, but it lives in its own
branch: a dedicated `People` root, sibling to the existing top-level
financial accounts, never nested under them. Interleaving would let a
person's balance get summed into a financial parent's rollup, which is not
what "money someone owes you" means.

Spec: `dev/specs/expense-splitting.md`

## Acceptance Criteria

- A `People` root account exists, separate from the cash/asset/expense
  trees — not a child of any existing top-level account.
- A migration seeds the `People` root (and any account-kind marker the
  architect's design calls for).
- A person account can be created as a leaf under `People` and posted to
  like any other leaf account (subject to the existing leaf-only posting
  rule).
- The existing account-tree listing shows `People` as a distinct top-level
  branch, alongside the other roots.
