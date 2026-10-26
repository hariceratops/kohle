# [feat] A reader refuses write commands up front

On a reader, a write command says why it cannot run instead of surfacing
SQLite's "attempt to write a readonly database".

Depends on: 060
Spec: `dev/specs/device-topology-and-sync.md`

## Acceptance Criteria

- With `ledger.mode = reader`, every command that writes the ledger (record,
  imports, `set-setting`, `migrate`, `init`, price fetching) exits non-zero
  with "this device is configured as a reader" and the config file path to
  edit.
- Nothing is written and no `Operation` is recorded.
- The message names no transport, tool or schedule.
- Read commands are unaffected.
- With `ledger.mode = writer`, behaviour is unchanged.
- Existing tests pass.
