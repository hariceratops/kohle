# [feat] A bad `config.toml` stops every command except `--help`

An unknown key, an invalid value or a TOML syntax error in `config.toml` is
caught before any command acts, so a typo cannot silently change behaviour.

Depends on: 055
Spec: `dev/specs/device-config.md`

## Acceptance Criteria

- An unknown key, an invalid value or a TOML syntax error makes every command
  exit non-zero before doing anything, including `init` and `migrate`.
- The error is one line naming the file and the key, and listing the known
  keys (unknown key) or the valid values (invalid value). A syntax error names
  the file.
- With `ledgr.path = "/x"` in the file, `list-accounts` exits non-zero naming
  the file and listing `ledger.path`, and `kohle-cli --help` still exits 0.
- Nothing is written to the ledger or the filesystem when the config is bad.
- Existing tests pass.
