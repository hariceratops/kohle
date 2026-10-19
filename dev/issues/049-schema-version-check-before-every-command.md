# [feat] Schema-version check before every command

Every command except `init`, `migrate` and `--help` verifies the ledger's
schema first, so a missing, behind or ahead database gives one clear line
instead of a stack trace.

Depends on: 047
Spec: `dev/specs/app-initialization.md`

## Acceptance Criteria

- Applies to reads and writes alike.
- No file at the path: "no ledger at <path>; run `kohle-cli init`", non-zero
  exit, and no file is created, not even an empty one.
- Revision behind head: one line pointing to `migrate`, non-zero exit.
- Revision ahead of head: one line saying to upgrade kohle, non-zero exit.
- Each case prints without a traceback.
- The check only reads the stored revision and never writes; it succeeds
  against `sqlite:///file:<path>?mode=ro&uri=true` of an up-to-date ledger.
- Only `init` and `migrate` may create or update `alembic_version`.
- Existing tests pass.
