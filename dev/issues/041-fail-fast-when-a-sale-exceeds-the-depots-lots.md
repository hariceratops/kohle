# [feat] Fail fast when a sale exceeds the depot's lots

A sale larger than the lots a depot holds means the ledger is inconsistent
(for example purchase history starts mid-way). The report refuses to print a
silently wrong profit.

Depends on: 040
Spec: `dev/specs/portfolio-and-profit-reporting.md`

## Acceptance Criteria

- When a sale or move-out exceeds the lots the depot holds, `realised` exits
  non-zero and prints no table.
- The message names the unit, the account, the entry date and the shortfall.
- The shortfall is returned as a domain `Err`, never raised; the CLI maps it
  to a non-zero exit like any other error.
- A missing or stale close is unaffected (not an error here).
- Existing tests pass unchanged.
