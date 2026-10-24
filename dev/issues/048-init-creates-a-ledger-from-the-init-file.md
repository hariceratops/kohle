# [feat] `init` creates a ledger from the per-user init file

`kohle-cli init` reads `init.rc`, runs the packaged migrations on a fresh
path and stores the settings, giving a new user a usable ledger in one
command. Introduces the settings table, its key list and validators, and a
listing that shows them.

Depends on: 047
Spec: `dev/specs/app-initialization.md`

## Acceptance Criteria

- `init` takes no flags and never prompts. Its only input is
  `$XDG_CONFIG_HOME/kohle/init.rc`, falling back to
  `~/.config/kohle/init.rc`; no other file is read and nothing is merged.
- The file is TOML, parsed with `tomllib`. The only key is `state`
  (`state = "BW"`). Keys come from a fixed list in code, each with its own
  validator; an unknown key lists the known keys, an invalid `state` lists
  the codes in `kohle.use_cases.sampling.STATES`.
- A missing file or a file without `state` exits non-zero naming the path
  looked at. The file is read and validated before anything is created, so
  any file error leaves no file at `KOHLE_DB`.
- On a path with no database, `init` creates the parent directory, migrates
  to head through Alembic's Python API (never `create_all`, never shelling
  out) and stores the settings.
- With `KOHLE_DB` at a fresh temp path and `XDG_CONFIG_HOME` at a temp dir
  holding `state = "BW"`: `init` then `list-accounts` shows the `People`
  root, and the settings listing shows `state = BW`, the database path and
  the schema revision. Whether that is the listing or a small `status`
  command is settled in the design.
- The recorded Alembic revision equals the code's head after `init`.
- The settings table's migration leaves `state` unset on existing ledgers;
  nothing assumes `BY`.
- Settings are written through `UnitOfWork`/`crud_create`, so they are
  audited.
- The README documents `init`, the init file's location, TOML format and
  `state` key.
- Existing tests pass.
