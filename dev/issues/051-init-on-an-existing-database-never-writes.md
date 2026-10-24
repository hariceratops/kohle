# [feat] `init` on an existing database never writes; a failed `init` leaves nothing

`init` run against a database that already exists only reports or points to
the right command, and an interrupted first-time `init` leaves nothing a
re-run would refuse.

Depends on: 048, 050
Spec: `dev/specs/app-initialization.md`

## Acceptance Criteria

- At head with a stored Bundesland equal to the file's `state`: prints
  "already initialized at <path>, revision <rev>", exits 0.
- Behind head: exits non-zero and points to `migrate`.
- At head with a stored Bundesland that differs from the file's `state` or is
  unset: exits non-zero and points to `set-setting state <code>`.
- None of these cases writes to the database.
- A file error (missing, invalid) is reported the same way whether or not a
  database exists.
- If a first-time `init` fails or is interrupted after creating anything, no
  half-built database is left: either no file, or nothing a re-run of `init`
  would refuse.
- Existing tests pass.
