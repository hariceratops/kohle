# [feat] `list-config` and `get-config <key>`

The effective device configuration can be inspected without opening the
ledger, which makes it the way to debug a wrong `ledger.path`.

Depends on: 055
Spec: `dev/specs/device-config.md`

## Acceptance Criteria

- `list-config` prints every known device key with its effective value and
  its source: `default`, `file`, or the overriding environment variable
  (`KOHLE_DB`).
- `get-config <key>` prints the effective value of one key. An unknown key
  exits non-zero and lists the known keys.
- Neither command opens the ledger or runs the schema-version check. With
  `ledger.path` pointing at a nonexistent file, `list-config` exits 0 and
  shows the path. They also work when the ledger is behind or ahead of the
  code.
- Both sit outside the `_LedgerCommand` schema check and never resolve an
  engine.
- Flat verb-object naming, as the existing commands. The spec's
  `config list` / `config get` are these two commands; the user chose flat
  names over a `config` subgroup.
- Both fail on a bad `config.toml` like every other command except `--help`;
  the error names the file and the key.
- Existing tests pass.
