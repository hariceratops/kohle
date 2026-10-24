# [feat] `net-worth-history` uses the stored Bundesland

`net-worth-history` takes the holiday calendar from the ledger's `state`
setting instead of a hidden `BY` default.

Depends on: 052
Spec: `dev/specs/app-initialization.md`

## Acceptance Criteria

- `--state` loses its `BY` default and stays as an optional per-run override.
- With no override and no stored value, the command exits non-zero and points
  to `set-setting state <code>`.
- On a ledger with `state` unset, `net-worth-history` without `--state` fails
  with that message; with `--state HE` it runs.
- With a stored value and no `--state`, the stored value is used.
- Reading the setting leaves no `OperationGroup` behind.
- No code path reaches a hidden `BY` default; cleaning up the remaining
  internal defaults in `sampling_dates` and `NetWorthHistory.execute` is left
  to `configurable-net-worth-sampling`.
- The README is updated for the changed `--state` behaviour.
- Existing tests pass.
