# [feat] Suggest minimum settling transfers

Naively pairing up every non-zero person balance overstates the number of
transfers actually needed to settle up — three people whose balances cancel
through one intermediary need one transfer, not three. This computes the
minimal set (debt simplification / min-cash-flow netting) instead.

Settling itself needs no new mechanism: a transfer from a person account to
a cash account is already representable with the existing entry model. This
issue only adds the suggestion; executing one is just posting an ordinary
transfer.

Depends on: 022
Spec: `dev/specs/expense-splitting.md`

## Acceptance Criteria

- Given a set of person balances — globally, or scoped to one group (021) —
  a command outputs the minimum set of settling transfers that zeroes them
  all out.
- Test: three people with net balances that cancel through one intermediary
  produce one suggested transfer, not two or three.
- The algorithm operates on current account balances computed at
  report/suggestion time — nothing about a suggestion is stored.
- Executing a suggested transfer (via the existing transfer entry path) and
  re-running the report confirms the involved balances have zeroed out.
