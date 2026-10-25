# [feat] `ledger.path` in `config.toml` selects the ledger

A per-device `config.toml` can name the ledger, so a machine's ledger location
is a fact about that machine instead of an environment variable.

Depends on: 054
Spec: `dev/specs/device-config.md`

## Acceptance Criteria

- The file is `$XDG_CONFIG_HOME/kohle/config.toml`, falling back to
  `~/.config/kohle/config.toml`. It is TOML; `[ledger]` / `path = "…"` and
  `ledger.path = "…"` are equivalent. kohle never writes it.
- A device-key registry, separate from the ledger `SETTINGS`, holds
  `ledger.path` with a validator returning `Result`.
- The file is read once per command, before any engine is created.
- With `XDG_CONFIG_HOME` and `XDG_DATA_HOME` pointing at temp dirs:
  - `ledger.path` set, `KOHLE_DB` unset: commands use `ledger.path`;
  - both set: `KOHLE_DB` wins;
  - neither set: the XDG default is used.
- A leading `~` in `ledger.path` is expanded. A relative path such as
  `kohle.db` is rejected by the validator.
- The validator checks form only. A path with no ledger behind it still gives
  the existing "no ledger at <path>; run `kohle-cli init`" error.
- A missing config file is not an error; every key takes its default.
- `kohle-cli`, `kohle-tui` and the repo's Alembic environment resolve the
  ledger the same way.
- Existing tests pass.
