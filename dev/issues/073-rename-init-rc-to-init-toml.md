# [chore] Rename init.rc to init.toml in code, messages and README

`device-config` named the file `init.toml` and scheduled the code rename as a
separate change. Do it before 069, which rewrites the same code, messages and
README section.

Depends on: none (lands before 069)
Spec: `dev/specs/device-config.md`; design: `dev/design/configurable-net-worth-sampling.md`

## Acceptance Criteria

- The init file is `init.toml` in code, error messages, tests and README.
- No reference to `init.rc` remains outside `dev/` history.
- `init` behaves exactly as before apart from the name.
- Existing tests pass, apart from those that assert the old name.
