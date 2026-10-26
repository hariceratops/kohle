# [feat] `list-settings` shows the path's source and `set-setting` refuses device keys

The ledger-settings commands keep the two scopes apart: the listing says where
the ledger path came from, and `set-setting` points a device key to the file.

Depends on: 055
Spec: `dev/specs/device-config.md`

## Acceptance Criteria

- `list-settings` still shows only ledger settings, the ledger path and the
  revision. The path line also shows its source (`default`, `file`, or
  `KOHLE_DB`).
- `set-setting ledger.path <value>` exits non-zero with
  "`ledger.path` is a device key; edit <config path>", naming the actual
  config file path. Nothing is written and no `Operation` is recorded.
- `set-setting` for ledger keys behaves as before, including the unknown-key
  error.
- Existing tests pass.
