# [feat] A device-config key marks a device as a reader, and reads work on it

A device can be configured to never write its ledger file — for example one
that holds a synced copy. It opens the file read-only and reports normally.

Depends on: 059
Spec: `dev/specs/device-topology-and-sync.md`

## Acceptance Criteria

- `ledger.mode` is a registered device key with values `writer` and `reader`;
  the default is `writer`, so a device that sets nothing behaves as before.
  `list-config` and `get-config` show it with its source.
- An invalid value is rejected like any bad device value, stopping every
  command except help.
- With `reader`, the engine URL opens the file with `mode=ro`; `balance`,
  `list-accounts` and the reports read a snapshot normally.
- With `reader`, a missing file fails with "unable to open database file"
  semantics and no empty database is created.
- Reader mode depends only on the config key: any ledger file can be opened
  read-only, whether or not it came from `snapshot`.
- Tests build their reader ledger from a `snapshot` and never read the real
  per-user config.
- Existing tests pass.
