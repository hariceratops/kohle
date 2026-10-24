# [feat] One per-user database location, with migrations shipped in the package

Every entry point resolves the ledger path the same way, independent of the
working directory, and the Alembic migrations move inside the `kohle`
package so an installed `kohle-cli` can reach them outside a checkout.

Depends on: none
Spec: `dev/specs/app-initialization.md`

## Acceptance Criteria

- Path is `KOHLE_DB` if set, else `$XDG_DATA_HOME/kohle/kohle.db`, else
  `~/.local/share/kohle/kohle.db`. No `--db` flag.
- `kohle-cli`, `kohle-tui` and the Alembic environment use the same
  resolution; the hard-coded `sqlite:///kohle.db` is gone from
  `kohle/db/connection.py` and `alembic.ini`.
- With `KOHLE_DB` unset and `XDG_DATA_HOME` at a temp dir, commands run from
  two different working directories read the same ledger.
- Migrations and their environment live inside the package; their location
  is resolved from the package, not from `alembic.ini`.
- `alembic revision --autogenerate` run from the repo still works and finds
  the database the same way kohle does.
- The CLI's session-factory injection still works; tests never touch the real
  per-user path.
- The README documents the location, `KOHLE_DB`, and the one-time manual move
  of an existing `./kohle.db`.
- Existing tests pass.
