# [chore] Inject the session factory into CLI commands

Every command in `kohle/app/cli/cli.py` constructs `session_local()` inline,
which is bound to the real `kohle.db`. A `CliRunner` test invoking any
command would therefore write to the user's actual ledger, so CLI behaviour
cannot be tested at all and automated coverage stops at the pure parsers.

Most of the acceptance criteria in issues 001-008 are statements about CLI
behaviour — that an unknown account name produces a clear error rather than a
traceback, that a malformed `--line` names the offending value, that a tree
renders with visible nesting. Without this, all of them are hand-verified
only.

`tests/conftest.py` already defines a `session_factory` fixture backed by
in-memory SQLite with `StaticPool`. No test uses it; it was written for
exactly this and never wired up.

Blocks meaningful testing of: 001-008. Worth doing before the test strategy
is written.

## Acceptance Criteria

- The `cli` group carries a session factory on Click's context object,
  defaulting to `session_local` so production behaviour is unchanged.
- Every existing command takes the factory from the context rather than
  calling `session_local()` directly.
- `CliRunner().invoke(cli, [...], obj=session_factory)` runs a command
  against an in-memory database, using the existing `conftest` fixture.
- No command's observable behaviour changes — this is plumbing only.
- At least one CLI test exists proving the injection works and that the real
  `kohle.db` is untouched during a test run.
- The 35 existing tests still pass.
