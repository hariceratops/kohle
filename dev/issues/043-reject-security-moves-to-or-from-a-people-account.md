# [feat] Reject security moves to or from a People account

A security moving between an own depot and a People account is neither a sale
nor an own-depot move. It is not supported for now, so the report fails
instead of guessing.

Depends on: 042
Spec: `dev/specs/portfolio-and-profit-reporting.md`

## Acceptance Criteria

- `realised` exits non-zero, naming the entry, when a security moves between
  an own depot and a People account, in either direction; no table is printed.
- The error is a returned `Err` mapped to a non-zero exit.
- Moves between two own depots (042) are unaffected.
- Existing tests pass unchanged.
