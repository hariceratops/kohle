# [feat] `set-setting <key> <value>`, audited

Settings can be changed after `init` from the CLI, each change validated and
recorded in the audit trail.

Depends on: 048
Spec: `dev/specs/app-initialization.md`

## Acceptance Criteria

- `set-setting state HE` stores the value and the settings listing shows it.
- Unknown key: error listing the known keys. Invalid value: error listing the
  valid values. Nothing is written in either case.
- Uses the same key list and per-key validators as `init`.
- Every change is recorded as an `Operation` and appears in
  `list-operations`.
- Flat verb-object naming, as the existing commands.
- Existing tests pass.
