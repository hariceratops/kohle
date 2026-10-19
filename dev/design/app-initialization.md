# Design: First-run initialization

Spec: `dev/specs/app-initialization.md` (frozen)
Issues: `dev/issues/047`–`053`
Precedents: `dev/design/price-fetcher-plugin.md` (create/update/no-op upsert
behind `set-price-source`), `dev/design/portfolio-and-profit-reporting.md` §7
(why a settings table, and in what form), cited as PP §n.

Layering stays as `AGENTS.md` describes it: `app -> use_cases -> services ->
infrastructure/domain`. Only services touch a `Session`. Functions return
`Result[T, E]`, and domain errors are `Exception` subclasses used as values.
`kohle/db/` counts as infrastructure. It knows SQLite, Alembic and files, and
nothing about settings.

The two choices the spec leaves to design are settled in §2 and §3. Where the
design had to pick behaviour the spec does not pin down, the pick is listed in
§17 for the user to confirm.

---

## 1. Summary of the shape

| File | Change | Issue |
|---|---|---|
| `alembic/` → `kohle/db/migrations/` | `git mv` of `env.py`, `script.py.mako` and `versions/`. `alembic/README` is dropped. Delete the leftover untracked `alembic/__pycache__` dirs so the directory is gone (§3.5). | 047 |
| `kohle/db/migrations/env.py` | Rewritten. A connection passed in `config.attributes` is used as is; otherwise the ledger is found through `ledger_path()`. The `sys.path` hack goes (§3.4). | 047 |
| `alembic.ini` | `script_location = kohle.db:migrations`. `sqlalchemy.url` is removed (§3.3). | 047 |
| `kohle/db/connection.py` | `ledger_path()`, `ledger_url(path)`, `make_engine(url)` and `make_session_factory(engine)`. The module-level `DATABASE_URL`, `engine` and `session_local` are removed. `base` stays (§4). | 047 |
| `kohle/db/schema.py` | **new**. 047: `SCRIPT_LOCATION`, `alembic_config()`. 048: `stored_revision`, `build_ledger`. 049: `HEAD_REVISION`, `check_schema`, `open_ledger`. 050: `build_ledger(copy_existing=True)`, `migrate_ledger`, `Migration` (§5). | 047–050 |
| `kohle/infrastructure/uow.py` | The dead `unit_of_work` decorator and its `session_local` import are removed. Nothing calls it. | 047 |
| `kohle/infrastructure/infra_errors.py` | `LedgerError` family (§5.7). | 048–050 |
| `kohle/domain/models.py` | `Setting` (§7.1). | 048 |
| `kohle/db/migrations/versions/<rev>_settings.py` | **new** migration: the `settings` table, no rows, and a downgrade that refuses if rows exist (§7.1). | 048 |
| `kohle/domain/domain_errors.py` | `SettingError` family (048), `SettingDiffers` (051), `StateNotSet` (053) (§7.6). | 048, 051, 053 |
| `kohle/services/setting_services.py` | **new**. `list_settings_service`, `ledger_info_service`, and `set_setting_service` over private create and update services (§7.3). | 048 |
| `kohle/use_cases/settings.py` | **new**. `SETTINGS` registry, `validate_settings`, `validate_init_settings`, `SetSettings`, `ListSettings`, `SettingsReport` (§7). | 048 |
| `kohle/use_cases/ledger.py` | **new**. `init_ledger` and `Initialized` (§8.2). | 048, 051 |
| `kohle/app/cli/cli.py` | 047: default factory from `ledger_path()`. 048: `_init_file_path`, `_read_init_file`, `init`, `list-settings`. 049: `_LedgerCommand` and `_KohleGroup`, replacing the group callback (§6). 050: `migrate`. 052: `set-setting`. 053: `--state` loses its default and the stored state is read. | 047–053 |
| `kohle/app/tui/tui.py`, `kohle/app/tui/widgets/table_editor/table_controller.py` | The TUI opens the ledger the way the CLI does and injects the factory (§12). | 047, 049 |
| `pyproject.toml` | `exclude` gains `"dev*", "docs*"` (§3.5). No dependency changes, and `uv.lock` is untouched. | 047 |
| `tests/conftest.py` | Autouse fixture that points `KOHLE_DB` and `XDG_CONFIG_HOME` at temp paths (§18.1). Ledger fixtures follow from 048. | 047, 048 |
| `README.md` | Location, `KOHLE_DB`, the one-time move and writing migrations (047); first run, `init.rc` and `list-settings` (048); `migrate` (050); `set-setting` (052); `--state` (053). | 047–053 |

---

## 2. Decision 1: path and revision go in `list-settings`, with no `status` command

**Decision.** `kohle-cli list-settings` prints every known setting, then the
database path and the stored schema revision. There is no `status` command.

```
state = BW

ledger:   /home/hari/.local/share/kohle/kohle.db
revision: 3c9e1a7b52d4
```

An unset key prints as `state = (unset)`.

The reasons:

- **A `status` command could only ever print the head revision.** The spec
  puts the schema check on every command except `init`, `migrate` and
  `--help`, so `status` would be checked too. It would run only when the
  ledger is current, which is exactly when its revision line is least
  informative. In the cases where path and revision matter (missing, behind,
  ahead), the check's own one-line error already names the path and both
  revisions (§5.7). A separate command would add a verb whose only real
  content is one path.
- **One command meets the acceptance criterion.** Issue 048 asks for
  `state = BW`, the path and the revision in "the settings listing". Putting
  all three in one listing means one command and one test.
- **The listing keeps them visibly apart from settings.** Settings print as
  `key = value`, the syntax `init.rc` uses. A listed line can be pasted into a
  new `init.rc`, and it reads like the spec's `state = BW`. Path and revision
  print below a blank line as `ledger:` and `revision:`, so they do not read
  as keys `set-setting` accepts.
- **`device-topology-and-sync` is where a status command has content.** That
  feature brings device role, snapshot age and last sync. It can introduce
  `status` with real content and move the two lines there. `cli-command-naming`
  renames commands anyway, so nothing here locks that in.

**Where the values come from.** `ListSettings` reads both from the open
connection, not from `ledger_path()`.

- The path comes from `PRAGMA database_list`: the file SQLite actually opened,
  with symlinks resolved.
- The revision comes from `stored_revision()` (§5.1).

So the listing never names a file other than the one it read. With an
injected in-memory factory the path is `''` and prints as `(in memory)`. A
`create_all` test database has no `alembic_version`, so its revision prints as
`(none)`.

---

## 3. Decision 2: migrations live in `kohle/db/migrations/`

### 3.1 Layout

```
kohle/db/
  __init__.py
  connection.py          base, ledger_path, ledger_url, make_engine, make_session_factory
  schema.py              revision reading, the check, staged build, migrate
  migrations/            no __init__.py
    env.py
    script.py.mako
    versions/            no __init__.py
      0001_init.py
      ...
      d4e7a8c15b92_prices_unique_per_day.py
      <rev>_settings.py  (048)
```

Why `kohle/db/migrations/`:

- **It sits with the code that owns the schema.** `base`, which the migrations'
  `env.py` targets for autogenerate, is in `kohle/db/connection.py`. The code
  that reads and drives revisions (`schema.py`) is next to it.
- **It is not called `alembic`.** `kohle/db/alembic/` would work with absolute
  imports, but every reader would have to check which `alembic` an import
  means. The repo-root `alembic/` directory already causes trouble: setuptools
  packages it as a top-level `alembic` namespace package (§3.5).
- **No `__init__.py`.** Alembic loads `env.py` and the version files by path,
  never by import. An `__init__.py` would make `versions/0001_init.py` look
  importable, under a module name that is not a valid identifier, and nothing
  needs that. Packaging includes them anyway (§3.5).

### 3.2 How code resolves the location

`kohle/db/schema.py`:

```python
SCRIPT_LOCATION = "kohle.db:migrations"

def alembic_config() -> "Config":
    from alembic.config import Config  # see §5.2 for why the import is local
    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    return config
```

- `package:dir` is Alembic's own package-resource notation. Alembic 1.18.3's
  `coerce_resource_to_filename` resolves it with
  `importlib.resources.files("kohle.db") / "migrations"`, which gives the
  installed package's directory, wherever that is.
- `Config()` reads no ini file. The location comes from the package, never
  from `alembic.ini` and never from the working directory. That is what lets
  an installed `kohle-cli` run `init` and `migrate` outside a checkout.
- `init`, `migrate`, the slow path of the check (§5.2) and the tests all build
  their config through this one function.

### 3.3 `alembic.ini`

```ini
[alembic]
script_location = kohle.db:migrations
```

The rest of the file stays: the logging sections give the `alembic` command
its INFO output. `sqlalchemy.url` is deleted, because `env.py` resolves the
database (§3.4).

Both the code constant and the ini name the location with the same string,
and both resolve it through the package, so neither depends on the
working-directory layout. They are not tied by code. Alembic's command line
needs `script_location` in its config file, and the in-code path must not
read that file, because the file is not shipped. If the two drift apart,
`alembic revision` writes to the wrong place, and a test catches that
(§18.1).

### 3.4 `env.py`

```python
from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context
import kohle.domain.models  # noqa: F401  registers every table on base.metadata for autogenerate
from kohle.db.connection import base, ledger_path, ledger_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = base.metadata


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # kohle's init and migrate pass the connection of the staged file they
    # are building (schema.py). Run from the repo's `alembic` command, there is
    # none, and the ledger is found the way every kohle command finds it.
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = create_engine(ledger_url(ledger_path()), poolclass=pool.NullPool)
    with engine.connect() as connection:
        _run(connection)
```

Offline mode stays as it is, with `url = ledger_url(ledger_path())`. The URL
only picks the dialect there.

What this gives:

- **In-code runs never reach the dev branch.** `init` and `migrate` always
  pass the staged file's connection (§5.5), so they never touch
  `ledger_path()`.
- **The dev branch opens `mode=rw`.** It cannot create a database at a
  mistyped `KOHLE_DB` (§4.2). A developer without a ledger runs `kohle-cli
  init` first, or points `KOHLE_DB` at one.
- **Foreign keys stay off.** Migrations run on a plain `create_engine` without
  the pragma listener, as they always have. `batch_alter_table` copies and
  drops tables, and it relies on foreign keys being off.
- **In-code runs print nothing.** They have no `config_file_name`, so
  `fileConfig` is skipped. Alembic's INFO lines do not leak into
  `kohle-cli init` output.

### 3.5 Packaging

- `[tool.setuptools.packages.find]` in `pyproject.toml` defaults to
  namespace discovery. That is why `kohle/app/cli/` ships without an
  `__init__.py`. For the same reason `kohle.db.migrations` and
  `kohle.db.migrations.versions` are found, and every version `.py` goes into
  the wheel. No `package-data` is needed. `script.py.mako` is not shipped; only
  `alembic revision` uses it, and that runs from the checkout.
- **This fixes a hazard that exists today.** `kohle.egg-info/top_level.txt`
  lists `alembic`, `dev` and `docs` beside `kohle`.
  - In a non-editable install, the repo's `alembic/env.py` and `versions/`
    would be written into site-packages' `alembic/` directory, which is the
    real Alembic package.
  - The move removes `alembic` from that list once the leftover untracked
    `alembic/__pycache__` directories are deleted.
  - Slice 047 also adds `"dev*", "docs*"` to `exclude`.
  - Run `uv sync` afterwards so the editable finder's `MAPPING` is
    regenerated without the stale `alembic` entry.
- **Manual check, once, in 047.** Run `uv build` and confirm the wheel lists
  `kohle/db/migrations/env.py` and `kohle/db/migrations/versions/*.py`, and no
  top-level `alembic/`, `dev/` or `docs/`. A wheel-building test would cost
  more than it guards.

### 3.6 Writing a migration (the dev flow)

```bash
alembic revision --autogenerate -m "..."   # from the repo root
```

- This compares `base.metadata` with the ledger at `ledger_path()`: the user's
  real ledger, or `KOHLE_DB` if set. Autogenerate only reads.
- The new file lands in `kohle/db/migrations/versions/`.
- From 049 on, the developer also sets `HEAD_REVISION` in `kohle/db/schema.py`
  to the new revision id. `tests/test_schema_check.py` fails until they do
  (§5.2).
- `alembic upgrade head` from the repo still works in place on the resolved
  ledger. That is a developer tool. The README tells users to run
  `kohle-cli migrate`, which builds the upgrade on a staged copy (§5.5).

---

## 4. Path resolution and connections (`kohle/db/connection.py`)

### 4.1 `ledger_path()`

```python
def ledger_path() -> Path:
    if db := os.environ.get("KOHLE_DB"):
        return Path(db)
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base / "kohle" / "kohle.db"
```

- **Resolved when called, never at import.** The CLI calls it when a command
  runs. A test that sets `KOHLE_DB` with `monkeypatch` after importing the CLI
  is therefore honoured. Under the old module-level `engine`, that was not
  possible.
- **An empty variable counts as unset.** This follows the XDG spec, and the
  walrus and truthiness checks give it for free.
- **`Path.home()` reads `HOME`.** Tests set `HOME` to exercise the fallback.
- **No `--db` flag**, and no other variable selects the database. This is as
  the spec requires.
- **Not `platformdirs`**, although it is already a dependency (§14, Build vs.
  buy).

### 4.2 `ledger_url(path)`, `make_engine(url)`, `make_session_factory(engine)`

```python
def ledger_url(path: Path) -> str:
    # mode=rw opens an existing file read-write and never creates one, so no
    # command can leave an empty kohle.db behind; only init builds a file
    # (schema.build_ledger). Quoted because SQLite URIs give '?', '#' and '%'
    # meaning, and an unquoted '?' in a directory name silently opens a
    # different file.
    return f"sqlite:///file:{quote(str(path))}?mode=rw&uri=true"

def make_engine(url: str) -> Engine:
    engine = create_engine(url)
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine

def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
```

`make_session_factory` keeps today's `session_local` options.

Checked against SQLAlchemy 2.0.46 and SQLite 3.45.1:

- **Quoting.** A quoted path with a space and a `?` opens the right file.
  SQLAlchemy passes the database part through unchanged and SQLite decodes
  `%XX`. The same path unquoted opened, and created, a file at the truncated
  path.
- **`mode=rw`.** On a missing path it raises `OperationalError: unable to open
  database file` and creates nothing.
- **`mode=ro`.** `PRAGMA foreign_keys=ON` succeeds, and reads work. This is
  the spec's "connection setup works on a `mode=ro` connection".

**Why the frontends open `mode=rw` and not `mode=ro`.** A read-only connection
cannot roll back a hot journal: SQLite returns `SQLITE_READONLY_ROLLBACK`. If
the check used `mode=ro` on the master, one crashed write would lock the user
out. Every command would refuse, and nothing would open the file read-write to
recover it. `mode=rw` meets the spec's real constraint just as well, because
it never creates a file. The `mode=ro` case is covered by `check_schema`
taking any engine (§5.3), and `device-topology-and-sync` swaps the URL.

---

## 5. Schema lifecycle (`kohle/db/schema.py`)

The module's docstring should state its one non-obvious rule: Alembic is
imported only inside the functions that run migrations or need the revision
graph.

### 5.1 `stored_revision(connection) -> str | None`

```python
def stored_revision(connection: Connection) -> str | None:
    found = connection.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
    )).first()
    if found is None:
        return None
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
```

It issues two `SELECT`s, so it works on `mode=ro`. It writes nothing, and it
never creates `alembic_version`. Alembic's `MigrationContext.get_current_revision`
would do the same, but at the import cost described in §5.2.

### 5.2 `HEAD_REVISION`: keep Alembic off the per-command path

Measured in this venv, warm:

- `import kohle.app.cli.cli` takes about 0.57 s.
- Importing any Alembic module costs another 0.22 s. `alembic/__init__`
  imports `context`, then `ddl`, then Mako's Pygments plugin.

That would add about 40% to every command, and more on the Pi. `sampling.py`
already imports `holidays` lazily to save 0.19 s (PP §6.4).

```python
# The packaged head, so the check on every command can compare without
# importing Alembic. tests/test_schema_check.py pins it to Alembic's head; a
# stale value only sends the check down the slow path, it never misclassifies.
HEAD_REVISION = "<settings revision from 048>"
```

- **Fast path.** If `stored == HEAD_REVISION`, the ledger is current and
  Alembic is never imported.
- **Slow path, only when the fast path misses.** Import Alembic and build
  `ScriptDirectory.from_config(alembic_config())`:
  - `stored == script.get_current_head()` means current. This branch only
    runs if the constant is stale.
  - `stored is None`, or `stored` among `{s.revision for s in
    script.walk_revisions()}`, means behind. History is linear, so any known
    revision other than head is an ancestor.
  - Anything else means ahead: a revision from a newer kohle. This covers the
    spec's "snapshot from an upgraded Pi read by an older install".
- **Truth comes from Alembic's revision graph.** The constant is only a cache.

### 5.3 `check_schema(path, engine) -> Result[str, LedgerError]`

```python
def check_schema(path: Path, engine: Engine) -> Result[str, LedgerError]:
    """Ok(revision) when the ledger is at the packaged head. Reads only."""
    try:
        with engine.connect() as connection:
            stored = stored_revision(connection)
    except DBAPIError as e:
        return Result.err(LedgerUnreadable(path, str(e.orig)))
    ...  # §5.2 classification -> Ok(stored) | LedgerBehind(path, stored, head) | LedgerAhead(path, stored)
```

- **It takes an engine, not a path**, so the caller picks the URL. The spec's
  testable case, a `sqlite:///file:<path>?mode=ro&uri=true` engine, is one
  test, and reader mode later needs nothing new. `path` is only for messages.
- **`DBAPIError` is caught** because a corrupt, locked or non-SQLite file is a
  real outcome. The spec asks for one line without a traceback.

### 5.4 `open_ledger(path) -> Result[sessionmaker[Session], LedgerError]`

```python
def open_ledger(path: Path) -> Result[sessionmaker[Session], LedgerError]:
    if not path.exists():
        return Result.err(NoLedger(path))
    engine = make_engine(ledger_url(path))
    return check_schema(path, engine).map(lambda _: make_session_factory(engine))
```

`path.exists()` exists for the message. `mode=rw` is what guarantees that
nothing is created, even if the file disappears between the two calls. The CLI
hook (§6) and the TUI (§12) both use this function, so the two frontends
cannot drift apart.

### 5.5 `build_ledger`: stage beside the ledger, then rename

```python
def build_ledger(
    path: Path,
    copy_existing: bool,
    populate: Callable[[sessionmaker[Session]], Result[object, E]] | None,
) -> Result[str, LedgerError | E]:
    """Migrate a staged file to head and let `populate` write into it, then
    move it onto `path`. The staged file starts as a copy of the ledger when
    `copy_existing`, else empty. On any failure `path` is as it was."""
```

The steps:

1. `target = path.resolve()`. A symlinked ledger is upgraded where it lives,
   and the link is not replaced by a regular file.
2. `target.parent.mkdir(parents=True, exist_ok=True)`. This is the spec's
   "creates the parent directory if needed".
3. Create the staged file with `tempfile.mkstemp(dir=target.parent,
   prefix=f".{target.name}.", suffix=".tmp")` and close the fd. It sits in the
   same directory, so the rename in step 7 is atomic and never crosses a
   filesystem.
4. If `copy_existing`, copy with the SQLite backup API:
   `sqlite3.connect(<rw uri>, uri=True).backup(sqlite3.connect(staged))`. That
   gives a consistent snapshot even with a journal present, which
   `shutil.copy` would not.
5. Upgrade to head on the staged file. Use an engine on `ledger_url(staged)`
   with `NullPool` and no foreign-key pragma, pass its connection through
   `config.attributes["connection"]`, and call `command.upgrade(config,
   "head")`. Return `ScriptDirectory.from_config(config).get_current_head()`.
6. If `populate` is given, build `make_engine(ledger_url(staged))`. This is the
   ordinary engine, foreign keys on, like every other write. Call
   `populate(make_session_factory(engine))`. On `Err`, return it.
7. `os.replace(staged, target)`.
8. Wrap steps 2 to 7 in `except (RuntimeError, DBAPIError, sqlite3.Error,
   OSError)`, which returns `LedgerBuildFailed(path, reason)`.
   - `RuntimeError` is how this repo's migrations refuse, as in
     `d4a2e6f0b917`.
   - `DBAPIError` covers any database failure through SQLAlchemy.
   - `sqlite3.Error` covers the backup API.
   - `OSError` covers `mkdir`, `mkstemp`, `replace` and a full disk.
9. In `finally`, dispose the populate engine if one was made, and call
   `staged.unlink(missing_ok=True)`. This runs on `KeyboardInterrupt` too.
   After a successful replace the staged name no longer exists, so the unlink
   does nothing.

The prototype was run in the scratchpad against the current 14 migrations. A
0-byte `mkstemp` file under a directory named `data dir?x` upgraded to
`d4e7a8c15b92` with the People root seeded. No `-journal` file was left, and a
`mode=ro` engine then read the revision.

Notes for the implementer:

- **SQLite's commit makes the staged file durable before the rename.** With
  the default `synchronous=FULL` in rollback-journal mode, every commit fsyncs
  the file, so no explicit fsync is needed. If power is lost before the
  directory entry is durable, the old ledger remains, which is still
  all-or-nothing.
- **`mkstemp` creates the file 0600**, so a ledger built or replaced by `init`
  or `migrate` is 0600. That suits personal financial data. It is listed in
  §17 because `migrate` changes the mode of an existing 0644 ledger.
- **`populate` is a callback** because `init` must write its settings inside
  the staged file, before the rename, through `UnitOfWork` and the crud
  decorators. `kohle/db` cannot import use cases. The forcing problem is in
  §14, Abstractions introduced.

### 5.6 `migrate_ledger(path) -> Result[Migration, LedgerError]`

```python
@dataclass(frozen=True, slots=True)
class Migration:
    before: str | None
    after: str
```

1. If the path does not exist, return `Err(NoLedger(path))`. That message
   points to `init`.
2. Open `make_engine(ledger_url(path))` and run `check_schema`, then dispose
   the engine. Opening read-write also rolls back any hot journal, so the
   backup in step 4 copies a clean file.
3. On `Ok(rev)`, return `Ok(Migration(rev, rev))`. The CLI prints "already at
   revision".
4. On `Err(LedgerBehind)`, return `build_ledger(path, copy_existing=True,
   populate=None).map(lambda head: Migration(err.stored, head))`.
5. Any other `Err`, ahead or unreadable, is returned as is. Ahead tells the
   user to upgrade kohle.

`migrate_ledger` lives here and not in `use_cases/`, because it has no
use-case content. It never opens a `Session`.

### 5.7 Errors (`kohle/infrastructure/infra_errors.py`)

The family follows the `domain_errors.py` convention: `__str__` is the
one-line user message, and the CLI prints it through
`click.ClickException(str(err))`.

| Class | Fields | Message |
|---|---|---|
| `LedgerError(Exception)` | | base |
| `NoLedger` | `path` | ``no ledger at {path}; run `kohle-cli init` `` (the spec's wording) |
| `LedgerBehind` | `path, stored, head` | ``ledger at {path} is at revision {stored or "none"}, this kohle needs {head}; run `kohle-cli migrate` `` |
| `LedgerAhead` | `path, stored` | `ledger at {path} is at revision {stored}, which this kohle does not know; upgrade kohle` |
| `LedgerUnreadable` | `path, reason` | `cannot read ledger at {path}: {reason}` |
| `LedgerBuildFailed` | `path, reason` | `building the ledger at {path} failed and left it as it was: {reason}` |
| `LedgerExists` | `path` | **048 only**, removed by 051: `a ledger already exists at {path}` |

---

## 6. The check hook in the CLI

### 6.1 Where: in the subcommand's `invoke`, not in the group callback

Click 8.3.1's `Group.invoke` runs the group callback before it calls
`cmd.make_context(...)`. That is `core.py` lines 1870–1871. `make_context`
parses the subcommand's arguments, including the eager `--help`. A check in
the group callback would therefore run before `kohle-cli list-accounts
--help` printed anything, and with no ledger it would fail instead of showing
help.

`Command.invoke(ctx)` runs after `make_context`. So:

```python
class _LedgerCommand(click.Command):
    """Opens and checks the ledger before the command body runs. It sits in
    invoke because Click runs the group callback before parsing the
    subcommand's arguments, and `<command> --help` must work with no ledger.
    A factory injected through obj (tests) is the caller's schema, unchecked."""

    def invoke(self, ctx: click.Context) -> object:
        if ctx.obj is None:
            opened = open_ledger(ledger_path())
            if opened.is_err:
                raise click.ClickException(str(opened.unwrap_err()))
            ctx.obj = opened.unwrap()
        return super().invoke(ctx)


class _KohleGroup(click.Group):
    # Every command declared on `cli` gets the check unless it opts out with
    # cls=click.Command, as init and migrate do.
    command_class = _LedgerCommand


@click.group(cls=_KohleGroup)
def cli() -> None:
    pass
```

How this behaves:

- **Every command is covered by default**, reads and writes alike, including
  `list-importer-plugins`. A new command added later gets the check without
  anyone remembering to add it.
- **`init` and `migrate` opt out** with `@cli.command(cls=click.Command)`.
  `Group.command` only fills in `command_class` when `cls` is not given.
- **`--help` is exempt automatically**, as are usage errors. Click exits during
  `make_context`, before `invoke`.
- **An injected factory skips the check.** The sub-context inherits `obj` from
  the root context. `CliRunner.invoke(cli, ..., obj=factory)` keeps working
  for all the existing tests, whose `create_all` databases have no
  `alembic_version`. Spec: "Tests set `KOHLE_DB` or inject a factory".
- **One message line and exit code 1**, with no traceback. That is what
  `ClickException` gives.

### 6.2 The slice before the hook (047, 048)

Until 049, the group callback becomes:

```python
ctx.obj = ctx.obj or make_session_factory(make_engine(ledger_url(ledger_path())))
```

`create_engine` connects lazily, so `--help` still works. On a missing file
the first query raises, with a traceback, until 049. 049 deletes this line and
adds §6.1.

### 6.3 The test seam

`tests/test_cli.py` changes in 047:

- `test_injected_factory_is_used_and_real_db_is_untouched` monkeypatches
  `kohle.app.cli.cli.ledger_path` to raise, in place of `session_local`.
- `test_default_obj_falls_back_to_session_local` is replaced. See the 047
  tests in §16.

`ledger_path` is called on the default path in both 047 and 049, so the seam
does not move when the hook does.

---

## 7. Settings

### 7.1 Table, model, migration

```python
class Setting(base):
    """One ledger-wide setting. Keys come from SETTINGS in
    kohle/use_cases/settings.py; value is the validator's canonical string."""

    __tablename__ = "settings"

    # An integer id, not the key, as primary key: the crud decorators record
    # entity.id into Operation.entity_id, an Integer.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (UniqueConstraint("key", name="uq_setting_key"),)
```

- **An unset key has no row.** `value` is `NOT NULL`, so "unset" has exactly
  one representation.
- **No `Archivable`**, as with `PriceBinding`. Settings are not soft-deleted,
  and the spec has no unset command.
- **Migration `<rev>_settings.py`** revises `d4e7a8c15b92`, `create_table` only.
  It inserts no rows, so existing ledgers come out with `state` unset (spec:
  "Existing ledgers stay honest").
- **Its downgrade copies `b3f9d2a41c70_price_bindings`.**
  `_refuse_if_unrepresentable` counts rows and raises `RuntimeError` naming the
  count, because settings are user declarations the ledger cannot rebuild.
  Then it calls `drop_table`.

### 7.2 Registry and validators (`kohle/use_cases/settings.py`)

```python
Validator = Callable[[object], Result[str, InvalidSettingValue]]

def _bundesland(value: object) -> Result[str, InvalidSettingValue]:
    if isinstance(value, str) and value in STATES:
        return Result.ok(value)
    return Result.err(InvalidSettingValue("state", value, f"one of {', '.join(STATES)}"))

# The keys init.rc and set-setting accept, in listing order. A later feature
# adds its key here, and init.rc, set-setting and list-settings follow.
SETTINGS: dict[str, Validator] = {"state": _bundesland}
```

- **Validators take `object`.** `set-setting` passes a `str` and `init.rc`
  passes whatever TOML parsed. `state = 1` therefore fails with the same
  "expected one of BB, …" message as `state = "XX"`, which is exactly the
  spec's "invalid `state` lists the valid codes". A future numeric key can
  accept both `25` and `"25"` in its own validator.
- **They return the canonical stored string.** For `state` that is the code
  itself.
- **`STATES` comes from `kohle.use_cases.sampling`.** That is the same tuple
  `net-worth-history --state` uses as its `click.Choice`, so the two cannot
  drift. Codes are case-sensitive, as `--state` is.

```python
def validate_settings(raw: Mapping[str, object]) -> Result[dict[str, str], SettingError]
def validate_init_settings(raw: Mapping[str, object]) -> Result[dict[str, str], SettingError]
```

- **`validate_settings`** goes through `raw` in order. The first unknown key
  gives `UnknownSetting(key, list(SETTINGS))`, and the first invalid value
  gives the validator's `Err`.
- **`validate_init_settings`** runs `validate_settings` first, then
  `MissingSettings([k for k in SETTINGS if k not in raw])` if that list is not
  empty. Unknown keys are checked first so that a typo (`stat = "BW"`) reports
  "unknown setting 'stat'; known settings: state" rather than "missing state".
- **Every registered key is required at init.** The spec lists only keys "a
  later feature requires at init" for this file. No `required_at_init` flag
  is added until some key needs to be optional (§14, Extension points).

### 7.3 Services (`kohle/services/setting_services.py`)

These follow `price_services.py`'s binding services one for one:

```python
@crud_retrieve
def list_settings_service(ctx) -> Result[list[Setting], SettingError]

@crud_create
def _create_setting_service(ctx, key: str, value: str) -> Result[Setting, SettingError]

@crud_update
def _update_setting_service(ctx, setting_id: int, value: str) -> Result[Setting, SettingError]

def set_setting_service(ctx, key: str, value: str) -> Result[Setting, SettingError]:
    """Create the key's row the first time, update it after. An identical
    value writes nothing, so a replay leaves no OperationGroup."""

@crud_retrieve
def ledger_info_service(ctx) -> Result[LedgerInfo, SettingError]:
    # PRAGMA database_list's "main" row gives the file SQLite opened ('' in
    # memory); stored_revision(session.connection()) gives the revision.
```

- **`LedgerInfo(path: str, revision: str | None)`** is a frozen, slotted
  dataclass.
- **Infrastructure errors** map to `SettingError(str(err))`, as `PriceError`
  does in the price services.

### 7.4 Use cases

```python
@dataclass(frozen=True, slots=True)
class SettingsReport:
    ledger: str
    revision: str | None
    values: dict[str, str | None]  # every key in SETTINGS, None when unset

class ListSettings(UnitOfWork[SettingsReport, SettingError]):
    def execute(self) -> Result[SettingsReport, SettingError]

class SetSettings(UnitOfWork[list[Setting], SettingError]):
    def execute(self, values: Mapping[str, object]) -> Result[list[Setting], SettingError]:
        # validate_settings(values), then set_setting_service per pair,
        # all in this one transaction
```

- **`ListSettings` serves three callers:** `list-settings`, the
  existing-ledger branch of `init` (§8.2) and `net-worth-history` (§11). It
  reads only through `crud_retrieve` services, so no `OperationGroup` is
  created, as PP §12 notes for reads. Stored rows whose key is not in
  `SETTINGS` are ignored. Such a row could only come from a newer kohle, and
  the check refuses those ledgers.
- **`SetSettings` is plural because `init` writes every file key in one
  transaction.** That gives one `OperationGroup` with one `create` per key.
  `set-setting` calls it with a one-entry mapping, so both paths go through
  the same validators and the same service by construction.
- **`init` validates twice:** once before anything is created (§8.2), and
  again inside `SetSettings`. The second pass is the use case's own,
  unconditional validation, not extra defensive code. Canonical values
  validate to themselves.

### 7.5 Audit

- **Every changing write is recorded.** A first set records
  `Operation(entity_type="settings", entity_id=<setting id>, action="create")`,
  and a change records `action="update"`. Both show in `list-operations`.
- **An identical value writes nothing and records nothing**, the same rule as
  `set_price_binding_service`. The spec's "every change" is honoured, and a
  no-op is not a change.
- **The old value is not kept**, the same as for every other entity:
  `Operation.field` and `Operation.state` stay unused. Recording old and new
  values belongs to `undo-delete-edit` (§15).

### 7.6 Errors (`kohle/domain/domain_errors.py`)

| Class | Fields | Message |
|---|---|---|
| `SettingError(Exception)` | | base; also wraps infrastructure failures |
| `UnknownSetting` | `key, known` | `unknown setting {key!r}; known settings: {", ".join(known)}` |
| `InvalidSettingValue` | `key, value, expected` | `invalid {key} {value!r}; expected {expected}` |
| `MissingSettings` | `keys` | `missing {", ".join(keys)}` (the CLI prefixes the `init.rc` path) |
| `SettingDiffers` (051) | `path, key, stored, wanted` | stored `None`: ``ledger at {path} has no {key}; set it with `kohle-cli set-setting {key} {wanted}` ``. Otherwise: ``ledger at {path} has {key} = {stored} but init.rc says {wanted}; init never changes an existing ledger, `kohle-cli set-setting {key} {wanted}` does`` |
| `StateNotSet` (053) | | ``no Bundesland stored in the ledger; run `kohle-cli set-setting state <code>`, or pass --state`` |


---

## 8. `init`

### 8.1 The init file (`kohle/app/cli/cli.py`)

```python
def _init_file_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else Path.home() / ".config"
    return base / "kohle" / "init.rc"

def _read_init_file(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise click.ClickException(f'no init file at {path}; create it with a line such as state = "BW"') from None
    except tomllib.TOMLDecodeError as e:
        raise click.ClickException(f"{path}: {e}") from None
```

- **It lives in `cli.py`, beside `init`, because only `init` reads the file.**
  This puts the spec's "nothing reads the file afterwards" in the structure: no
  module below the app layer knows `init.rc` exists. It follows the
  `_parse_line` and `_parse_share` precedent: input parsing in the CLI raises
  Click exceptions, and the use case receives parsed values.
- **One file, no merging.** Only this path is looked at: no `./.kohlerc` and
  no system-wide file.
- **The file is only read, never written**, so it has no lifecycle of its own.

### 8.2 `init_ledger(path, settings)` (`kohle/use_cases/ledger.py`)

```python
@dataclass(frozen=True, slots=True)
class Initialized:
    path: Path
    revision: str
    created: bool

InitError = LedgerError | SettingError

def init_ledger(path: Path, settings: Mapping[str, str]) -> Result[Initialized, InitError]:
```

`settings` must come from `validate_init_settings`. `init_ledger` is the one
use case that opens its own engines rather than receiving a `Session`, because
deciding which file to open (the real one or a staged one) is its job.

**048: the path does not exist.**

```python
built = build_ledger(path, copy_existing=False,
                     populate=lambda make_session: SetSettings(make_session()).execute(settings))
return built.map(lambda rev: Initialized(path, rev, created=True))
```

If the path exists, 048 returns `Err(LedgerExists(path))` without opening the
file. That is scaffolding (§16).

**051: the path exists.** Nothing is written in any branch.

1. `engine = make_engine(ledger_url(path))`, then `check_schema(path, engine)`.
   On `Err`, return it: behind points to `migrate`, ahead to upgrading kohle,
   and unreadable says so. The settings table may not exist when behind, so
   nothing else is read.
2. Otherwise `ListSettings(make_session_factory(engine)()).execute()`, which
   reads only.
3. For each `key, wanted` in `settings`: if `report.values[key] != wanted`,
   return `Err(SettingDiffers(path, key, report.values[key], wanted))`. A
   stored `None` also differs.
4. Otherwise return `Ok(Initialized(path, revision, created=False))`.

### 8.3 The `init` command

```python
@cli.command(cls=click.Command)   # cls from 049 on (§6.1)
def init_cmd() -> None:
    rc = _init_file_path()
    raw = _read_init_file(rc)
    validated = validate_init_settings(raw)
    if validated.is_err:
        raise click.ClickException(f"{rc}: {validated.unwrap_err()}")
    path = ledger_path()
    res = init_ledger(path, validated.unwrap())
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    done = res.unwrap()
    if done.created:
        click.echo(f"Initialized ledger at {done.path}, revision {done.revision}")
    else:
        click.echo(f"already initialized at {done.path}, revision {done.revision}")
```

- **The order is the spec's guarantee.** Read, then validate, and only then
  call `ledger_path()` and `init_ledger`. Any file error exits before anything
  is created.
- **File errors are reported the same way whether or not a database exists**
  (051).
- **No flags and no prompts.** `init` takes no `click.option` and no
  `click.prompt`.

---

## 9. `migrate`

```python
@cli.command(cls=click.Command)
def migrate_cmd() -> None:
    path = ledger_path()
    res = migrate_ledger(path)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    m = res.unwrap()
    if m.before == m.after:
        click.echo(f"ledger at {path} is already at revision {m.after}")
    else:
        click.echo(f"Migrated ledger at {path} from revision {m.before or 'none'} to {m.after}")
```

The outcomes:

| State | Result | Exit |
|---|---|---|
| At head | reports so | 0 |
| No file | points to `init`, creates nothing (`exists()` check, then `mode=rw`) | 1 |
| Ahead | says to upgrade kohle | 1 |
| Behind | staged copy, upgrade, rename; reports the new revision | 0 |
| Failure while building | the ledger keeps its old file, revision and data | 1 |

A file without `alembic_version` (an empty 0-byte file, say) counts as behind
from `none`. `migrate` then builds the full schema with `state` unset, the same
as a migrated old ledger. A foreign SQLite file whose tables collide fails in
the staged copy and is left untouched.

---

## 10. `set-setting` and `list-settings`

```python
@cli.command()
@click.argument("key")
@click.argument("value")
@click.pass_obj
def set_setting_cmd(make_session, key: str, value: str):
    res = SetSettings(make_session()).execute({key: value})
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    click.echo(f"Set {key} to {value}")
```

- **`KEY` is a plain argument, not a `click.Choice`.** A `Choice` would turn an
  unknown key into a Click usage error (exit 2) with Click's own wording,
  outside the shared registry path. With a plain argument, `init` and
  `set-setting` produce the same `UnknownSetting` text.
- **On an unknown key or an invalid value, nothing is written.** Validation
  returns `Err` before any service runs, and `DbTransaction` rolls back on
  `Err` regardless.
- **The names keep the flat verb-object style:** `set-setting`,
  `list-settings`. Click strips `_cmd`.

`list_settings_cmd` renders `SettingsReport` as in §2.

---

## 11. `net-worth-history`

- `--state` keeps `type=click.Choice(STATES)` and gets `default=None`.
  `show_default` is dropped. The help becomes: "Bundesland whose public
  holidays are not working days, for this run only; defaults to the ledger's
  `state` setting; ignored with month-end".
- After the existing `--to` and `--from` checks, and before
  `NetWorthHistory(...)`:

  ```python
  if state is None:
      listed = ListSettings(make_session()).execute()
      if listed.is_err:
          raise click.ClickException(str(listed.unwrap_err()))
      state = listed.unwrap().values["state"]
      if state is None:
          raise click.ClickException(str(StateNotSet()))
  ```

  Doing this after the date checks keeps
  `test_net_worth_history_usage_errors_exit_2_without_opening_a_session`
  true: a usage error still opens no session.
- **`NetWorthHistory.execute` and `sample_dates` are unchanged.** Their `"BY"`
  defaults stay, because the CLI now always passes a state, so no path reaches
  them. Issue 053 leaves removing them to `configurable-net-worth-sampling`.
- **The settings read is its own read-only `UnitOfWork`.** It leaves no
  `OperationGroup`, and
  `test_new_reports_leave_prices_operations_and_groups_untouched` proves it
  once its setup stores a state (§18).
- **Why the CLI resolves the state and `NetWorthHistory` does not:** see §15.

---

## 12. The TUI

`kohle-tui` cannot start today. `tui.py` imports `category_screen`, which
imports the missing `kohle.app.tui.widgets.category_form` and
`kohle.use_cases.debit_categories`; this was checked. The only TUI module that
touches the database, `table_controller.py`, imports the `session_local` that
047 removes. The minimal coherent change:

- **`table_controller.py`.** `TableController.__init__` gains `make_session:
  Callable[[], Session]`, and the three `session_local()` calls become
  `self.make_session()`. `TableControllerBuilder.build(make_session)` passes it
  through. Nothing constructs either class today.
- **`tui.py`.**
  - 047: `main()` builds the factory as the CLI's 047 default does (§6.2).
  - 049: `main()` calls `open_ledger(ledger_path())` and exits with
    `sys.exit(str(err))` on `Err` (message to stderr, exit 1).
  - In both, `main()` passes the factory to `KohleApp(make_session)`, which
    stores it. That is the seam `tui-wiring` hands to
    `TableControllerBuilder.build`.

This cannot be exercised until `tui-wiring` fixes the imports, so review
verifies it, not a test (§17).

---

## 13. README

| Slice | Section |
|---|---|
| 047 | **Where the ledger lives:** the `KOHLE_DB` / `$XDG_DATA_HOME/kohle/kohle.db` / `~/.local/share/kohle/kohle.db` order; no `--db`; `KOHLE_DB` the only selector. **One-time move:** `mkdir -p ~/.local/share/kohle && mv ./kohle.db ~/.local/share/kohle/kohle.db`, by hand, once. **Writing migrations:** §3.6, with a note that `alembic upgrade` is a developer tool. |
| 048 | **First run:** `init.rc` at `$XDG_CONFIG_HOME/kohle/init.rc` or `~/.config/kohle/init.rc`; TOML, the `state` key with the 16 codes; read once by `init`, never afterwards; `kohle-cli init`; `list-settings`. |
| 049 | One paragraph: every command checks the schema first, with the three messages. |
| 050 | `migrate`. Complete the one-time move with "then run `kohle-cli migrate`". |
| 052 | `set-setting`, audited, with an example. The move sequence ends with "then `kohle-cli set-setting state <code>`", because a migrated ledger has no state. |
| 053 | Replace "(default `BY` …)" in *Net worth over time*: the state comes from the `state` setting; `--state` overrides it for one run; with neither, the command refuses. |

`AGENTS.md`'s Context should gain one sentence after landing. This design does
not edit it; the user does. Suggested: "The ledger lives at `KOHLE_DB` or
`$XDG_DATA_HOME/kohle/kohle.db`; its schema is created and upgraded only by
`kohle-cli init` and `migrate`, from the Alembic migrations packaged in
`kohle/db/migrations/`, and every other command checks its revision first.
Ledger-wide settings live in the `settings` table, keyed by the registry in
`kohle/use_cases/settings.py`, never in environment variables."

---

## 14. The decision categories

### State and data lifecycle

- **`init` is one unit:** the schema at head plus every `init.rc` setting.
  - It is built in a staged file beside the ledger and published by one
    `os.replace`.
  - Before the rename nothing exists at the ledger path; after it, a complete
    ledger does.
  - A failure or Ctrl-C removes the staged file (`finally`). A hard kill can
    leave a hidden `.kohle.db.XXXX.tmp`, but never anything at the path, so a
    re-run of `init` proceeds. The spec's "either no file, or nothing a re-run
    would refuse" holds by construction.
- **`migrate` is one unit:** a backup-API copy plus every pending migration.
  It is published by the same rename. Until the rename the original is
  untouched, so a failure or interruption leaves the old revision and data
  byte for byte.
- **Why staging and not a transaction.** pysqlite in its default mode
  autocommits DDL, so in-place migrations are not atomic today (§15).
- **`set-setting` is one `UnitOfWork` transaction:** validate, upsert, record
  the `Operation`. An `Err` rolls back.
- **Reads write nothing.** The check, `list-settings`, the existing-ledger
  branch of `init` and the settings read in `net-worth-history` leave no
  `OperationGroup`. The check never touches `alembic_version` beyond a
  `SELECT`. Only `build_ledger`, so only `init` and `migrate`, ever creates or
  updates it.
- **All three writers are replayable and idempotent.**
  - Re-running `init` with the same file on its own ledger exits 0, "already
    initialized".
  - `migrate` at head exits 0.
  - `set-setting` with the current value writes nothing.
- **Auditable.**
  - Setting changes are `Operation` rows (§7.5). `init`'s settings form the new
    ledger's first `OperationGroup`.
  - Schema changes are recorded only in `alembic_version`. A migration is not a
    ledger entity change, so it gets no `Operation`.
  - No old values are kept, as with every other entity.
- **Reversible?**
  - Settings changes, only by setting the old value again. There is no undo
    until `undo-delete-edit`.
  - Migrations have downgrades, but kohle exposes no downgrade command; they
    stay a developer tool. The settings downgrade refuses while rows exist.
- **No module-level mutable state remains** in `kohle/db/`. The old import-time
  `engine` and `session_local` are gone.

### Error propagation

The failure paths, and where each changes form:

| From | Caught where, as what | Becomes |
|---|---|---|
| SQLAlchemy and sqlite errors inside a use case | `DbTransactionContext.run` → `InfrastructureError` → service `map_err` | `SettingError`. The existing AGENTS.md override covers this seam; nothing new. |
| Reading the revision | `check_schema`: `except DBAPIError` | `LedgerUnreadable` |
| Building or migrating | `build_ledger`: `except (RuntimeError, DBAPIError, sqlite3.Error, OSError)` (§5.5) | `LedgerBuildFailed`. Anything else is a bug and shows a traceback; the staged file is still removed in `finally`. No new broad `except Exception`. |
| `init.rc` I/O and syntax | `cli.py`: `FileNotFoundError`, `tomllib.TOMLDecodeError` | `click.ClickException` naming the path |
| Validation and settings comparison | | `SettingError` values. Validation runs before any write in both callers. |
| Every `Err` reaching the CLI | | `click.ClickException(str(err))`: `Error: <one line>`, exit 1. Usage errors stay exit 2. |

What each layer knows about the one below:

- **The CLI** knows Click, the `init.rc` path and the error messages. It does
  not know Alembic or SQLite.
- **`use_cases/ledger.py` and `use_cases/settings.py`** know the registry and
  the `schema.py` functions. They do not know Alembic, file staging or SQL.
- **`schema.py`** knows SQLite, files and Alembic. It does not know settings:
  `populate` is opaque to it.
- **`env.py`** knows Alembic and `ledger_path`.

### Concurrency and ownership

- **Single-threaded.** Each CLI process makes one engine per invocation,
  owned by the Click context through `ctx.obj`. There is no shared mutable
  state in-process.
- **Across processes, SQLite file locking protects the ledger**, as before.
  New in this feature:
  - **The staged file belongs to the process that `mkstemp`'d it.** The name
    is unique, and nothing else opens it.
  - **During `migrate`, no up-to-date kohle can write the old file.** Once the
    new code is installed, every other command sees "behind" and refuses.
    Only a long-lived process running old code could still write to the
    replaced inode. Today that would be the TUI, which cannot start (§17).
  - **Two `init`s at once could clobber each other.** `os.replace` overwrites
    a ledger a concurrent `init` created between the existence check and the
    rename. Both are fresh ledgers, so nothing is lost unless the user also
    records into the first within that window. This is accepted (§15).
- **The check runs once per command, before the body.** A ledger replaced by a
  concurrent `migrate` mid-command is not re-checked. The command finishes on
  the inode it opened.

### Reuse

What this uses rather than rebuilds:

- `UnitOfWork`, `DbTransactionContext`, and `crud_create`, `crud_update`,
  `crud_retrieve` for every settings read and write.
- `set_price_binding_service`'s create / no-op / update shape, copied for
  `set_setting_service`.
- `STATES` from `sampling.py`, as the `state` validator's set.
- The `_refuse_if_unrepresentable` downgrade pattern from
  `b3f9d2a41c70_price_bindings`.
- The `test_migration_downgrade.py` harness.
- The read-only guard test in `test_price_guards.py`.
- The `click.ClickException(str(domain_error))` rendering and
  error-class-with-`__str__` conventions.
- Alembic's package-resource `script_location` and its documented
  "connection in `config.attributes`" pattern.

What is factored here so the next feature reuses it:

- **`SETTINGS`, `SetSettings`, `ListSettings`.**
  `configurable-net-worth-sampling` and `budgeting` add keys and must not build
  a second mechanism (spec).
- **`ledger_url` and `make_engine`.** Reader mode changes `mode=rw` to
  `mode=ro` in one place.
- **`check_schema(path, engine)`.** Engine-agnostic, for a reader's snapshot.
- **`build_ledger`.** Any later "rebuild the file and swap it in", such as
  restoring a snapshot, can reuse the staging.

### Extension points

1. **`SETTINGS`.** The contract:
   - A key is a string.
   - Its validator takes the raw value (`str` from `set-setting`, any TOML
     value from `init.rc`) and returns the canonical `str` or
     `InvalidSettingValue` with a human `expected`.
   - The canonical string is what is stored.
   - Readers see `str | None`.
   - Every registered key is required in `init.rc`. When a key should be
     optional at init, that feature adds a per-key flag; do not add it before.
   - Adding a key needs no migration, because the table is key/value.
     Existing ledgers simply have the new key unset; its consumer refuses and
     points to `set-setting`, the pattern §11 sets for `state`.
2. **`_KohleGroup.command_class`.** New commands get the check by default.
   Opting out (`cls=click.Command`) is reserved for commands that must run on
   a missing or outdated ledger. Today that means `init` and `migrate`.
3. **`kohle/db/migrations/versions/` plus `HEAD_REVISION`.** A new migration
   is a new file plus bumping the constant; the pin test enforces the bump.
4. **`check_schema`'s engine parameter** is the reader-mode seam for
   `device-topology-and-sync`.
5. **No plugin-facing extension points** are added. Plugins read their own
   environment variables, as before.

### Build vs. buy

| Component | Decision | Evaluated, and why not |
|---|---|---|
| XDG path resolution | **Build** (3 lines each) | `platformdirs`, already a dependency. Its `user_data_dir` matches on Linux but returns `~/Library/Application Support` on macOS, `%LOCALAPPDATA%` on Windows and an app-private directory on Android. The spec fixes XDG semantics, and the device topology may include more than Linux boxes. |
| `init.rc` parsing | **Buy**: `tomllib` | Fixed by the spec. No dependency added. |
| Running migrations | **Buy**: Alembic's Python API | Fixed by the spec: no shell-out, no `create_all`. |
| Reading the stored revision | **Build** (two `SELECT`s) | Alembic's `MigrationContext.get_current_revision()` does the same but costs 0.22 s of imports on every command (§5.2). |
| Head and behind/ahead classification | **Buy**, behind a cached constant | Alembic's `ScriptDirectory`. Parsing `versions/*.py` with `ast` would avoid the import on the slow path too, but it would reimplement the revision graph. |
| Atomic publish | **Build** on stdlib `tempfile` and `os.replace` | `os.link` + `unlink` (no-clobber) fails on filesystems without hard links (§15). `atomicwrites` and friends write byte streams; they do not help SQLite build a file. |
| Copying the ledger | **Buy**: SQLite's backup API | `shutil.copy` can tear against a journal or a concurrent writer. |
| Settings storage | **Build**: one table through the crud decorators | `PRAGMA user_version` holds one integer. `sqlitedict` and `configparser` cannot be audited as `Operation`s, and the spec requires the audit. |
| Default-on command hook | **Buy**: Click's `Group.command_class` | The group callback runs too early (§6.1). A per-command decorator would be opt-in and easy to forget. |

### Abstractions introduced

Each one, with the problem that forces it:

| Abstraction | Forcing problem |
|---|---|
| `ledger_path()` | The spec's resolution order is read by four callers: CLI, TUI, `env.py`, tests. It must run when the command runs, not at import. |
| `ledger_url(path)` | Two properties every connection needs: `mode=rw`, so no command ever creates the file, and percent-quoting, because an unquoted `?` opened a different file in testing. |
| `make_engine(url)` / `make_session_factory(engine)` | They replace the import-time global. They take a URL and an engine because the check, the staged build and reader mode each open a different file or mode. |
| `HEAD_REVISION` | 0.22 s of Alembic imports per command (§5.2). |
| `check_schema(path, engine)` | One classification used by the per-command hook, `migrate` and `init`'s existing branch. The engine parameter is the spec's `mode=ro` testable. |
| `open_ledger(path)` | The CLI and the TUI must open and check the ledger identically. |
| `build_ledger(..., populate)` | `init` and `migrate` share the stage-and-rename mechanism. `populate` exists because `init`'s settings must be written inside the staged file through use-case-layer code, which `kohle/db` cannot import. |
| `Migration`, `Initialized` | Each command has two success outcomes with different messages, both exit 0. They are single dataclasses with a discriminating field (`before == after`, `created`), not unions. |
| `_LedgerCommand`, `_KohleGroup` | The check must run after `--help` parsing (§6.1), on every command by default. |
| `Setting` with an integer `id` | `Operation.entity_id` is an `Integer`. |
| `SETTINGS`, `validate_settings`, `validate_init_settings` | The spec requires one key list and one validator per key, shared by `init` and `set-setting`. |
| `SetSettings` (plural) | One `init` is one transaction and one `OperationGroup` across all keys. |
| `ListSettings` / `SettingsReport` | Three callers need stored values; the listing also needs the path and revision. |
| `LedgerInfo` and `ledger_info_service` | The listing must name the file actually read. Only a service may touch the `Session`. |

**Not introduced:**

- a `status` command;
- a typed settings object or attribute access (`settings.state`);
- a generic config layer, environment-variable fallbacks or a
  `required_at_init` flag;
- a `kohle/paths.py` module: the init-file path stays private to `cli.py`;
- an outcome union per command.

---

## 15. Alternatives rejected

- **A `status` command** for path and revision. See §2: the check gates it, so
  it would only ever show head. `device-topology-and-sync` is where it earns
  its keep.
- **Migrations at `kohle/migrations/` or `kohle/alembic/`.** Top-level
  `kohle/migrations/` would separate them from `base` and `schema.py` for no
  gain. `kohle/alembic/` makes `alembic` mean two things to every reader.
- **Resolving the location with
  `Path(__file__).parent / "migrations"`.** It works, but the string form
  `kohle.db:migrations` is what `alembic.ini` must use anyway. One spelling in
  both places reads better than two.
- **In-code `Config("alembic.ini")`.** The ini is not shipped and is found
  relative to the working directory. Both are what the spec removes.
- **An in-place, single-transaction `migrate`.**
  - The problem: pysqlite in its default mode does not emit `BEGIN` before
    DDL, so `CREATE`, `DROP` and `ALTER` autocommit and an interrupted
    multi-migration upgrade leaves a half-migrated schema.
  - The fix would be SQLAlchemy's pysqlite recipe (`isolation_level=None` plus
    a `BEGIN` on the `begin` event) on the migration engine.
  - Why not: `init` would still need staging, because an interrupted in-place
    `init` leaves a file a re-run refuses. One mechanism for both is simpler
    than two.
- **`mode=ro` for the check on the master.** It cannot roll back a hot
  journal, so it would lock the user out after a crash (§4.2). `mode=rw`
  already guarantees no file is created.
- **The check in the group callback.** It runs before `--help` (§6.1).
- **A lazy check on the first `make_session()`.**
  - It is not "every command": `list-importer-plugins` never opens a session.
  - Some commands do work before opening one. `import-statement` runs the
    plugin over the file first, so it would run against a broken ledger.
- **Checking injected factories too.** Test factories are `create_all`-built
  with no `alembic_version`. Checking them would mean stamping in every
  fixture, which is a test-only write to `alembic_version`, for no coverage
  gain: the check has its own file-based tests.
- **`MigrationContext` for the per-command read.** The import cost (§5.2).
- **`os.link` + `unlink` for a no-clobber `init` publish.** Hard links are not
  available on every filesystem, and the clobber window only matters for two
  simultaneous `init`s, which produce equivalent fresh ledgers.
- **The settings key as primary key.** It breaks `Operation.entity_id`, an
  integer.
- **Append-only settings history**, one row per change with the latest
  winning. It would keep old values, but every read would need a
  max-per-key subquery: the reason `Classification` is one row per entry. The
  `Operation` trail already records that a change happened.
- **Recording old and new values in `Operation.field` and `Operation.state`.**
  That changes `_record_write` for every entity. It belongs to
  `undo-delete-edit`.
- **`click.Choice(SETTINGS)` for `set-setting KEY`.** A different error path
  and exit code from `init`'s unknown key (§10).
- **`NetWorthHistory.execute(state: str | None)`, reading the setting inside
  its own transaction.** It is better encapsulated, but it means changing the
  use case's signature and error type (`ValuationError | SettingError`), and
  issue 053 leaves `execute`'s `"BY"` default to
  `configurable-net-worth-sampling`. That feature reworks how sampling reads
  its settings anyway, and can move the resolution inward then.
- **An environment variable, or `click.option(envvar=...)`, for `state`.**
  The spec forbids it, and PP §7 rejected it.
- **`platformdirs` for paths.** See Build vs. buy.
- **Writing settings after the rename in `init`.** A crash between the two
  would leave a head-revision ledger with `state` unset, which a re-run of
  `init` refuses.

---

## 16. Issue mapping and per-slice files

**Order: 047 → 048 → 049 → 050 → 051 → 052 → 053.** This is the issues' own
dependency order, linearised. 048 and 049 both edit `cli.py` and
`schema.py`, so they land in sequence.

### 047: per-user location, packaged migrations

Production changes:

- `git mv alembic/env.py alembic/script.py.mako alembic/versions
  kohle/db/migrations/`. Drop `alembic/README`, then remove the leftover
  `alembic/` directory (untracked `__pycache__`).
- `kohle/db/migrations/env.py` as in §3.4.
- `alembic.ini`: as in §3.3.
- `kohle/db/connection.py`: as in §4.
- `kohle/db/schema.py` (new): `SCRIPT_LOCATION` and `alembic_config()` only.
- `kohle/infrastructure/uow.py`: delete `unit_of_work` and the `session_local`
  import.
- `kohle/app/cli/cli.py`: the group callback default (§6.2). Import
  `ledger_path`, `ledger_url`, `make_engine` and `make_session_factory` in
  place of `session_local`.
- `kohle/app/tui/widgets/table_editor/table_controller.py` and
  `kohle/app/tui/tui.py`: as in §12, 047 form.
- `pyproject.toml`: add `"dev*", "docs*"` to `exclude`. Then `uv sync`, and
  check the wheel by hand once (§3.5).

Tests:

- `tests/conftest.py`: the autouse fixture (§18.1).
- `tests/test_cli.py`: the two `session_local` tests (§6.3).
- `tests/test_migration_downgrade.py`: the fixtures use `alembic_config()`,
  `db.touch()` and `monkeypatch.setenv("KOHLE_DB", ...)` instead of the
  ini path and `sqlalchemy.url`.
- `tests/test_ledger_location.py` (new), covering:
  - `KOHLE_DB` wins over `XDG_DATA_HOME`;
  - `XDG_DATA_HOME` is used when `KOHLE_DB` is unset or empty;
  - `HOME/.local/share` is the fallback;
  - two working directories read the same ledger, through `CliRunner` with no
    `obj` (the ledger is made with `db.touch()` plus
    `command.upgrade(alembic_config(), "head")`);
  - `ScriptDirectory.from_config(alembic_config())` finds a head with
    `monkeypatch.chdir(tmp_path)`, outside the checkout;
  - `alembic.ini`'s `script_location` equals `SCRIPT_LOCATION`.

README: as in §13.

### 048: `init` from the init file, settings table, `list-settings`

Production changes:

- `kohle/domain/models.py`: `Setting`.
- `kohle/db/migrations/versions/<rev>_settings.py`.
- `kohle/domain/domain_errors.py`: `SettingError`, `UnknownSetting`,
  `InvalidSettingValue`, `MissingSettings`.
- `kohle/infrastructure/infra_errors.py`: `LedgerError`, `LedgerBuildFailed`,
  and `LedgerExists` (interim).
- `kohle/db/schema.py`: `stored_revision`, and `build_ledger` with
  `copy_existing=False` only.
- `kohle/services/setting_services.py` (new).
- `kohle/use_cases/settings.py` (new).
- `kohle/use_cases/ledger.py` (new): `init_ledger`, creation path. An existing
  path gives `LedgerExists`.
- `kohle/app/cli/cli.py`: `_init_file_path`, `_read_init_file`, `init_cmd`,
  `list_settings_cmd`.

Tests:

- `tests/test_migration_downgrade.py`: `BEFORE_SETTINGS = "d4e7a8c15b92"`; a
  round trip when empty; a refusal when a row exists.
- `tests/test_settings.py` (new): registry and validators, and
  `ListSettings` with unset keys.
- `tests/test_init.py` (new): the spec's testable cases (§18.2).

README: as in §13.

**Scaffolding:** `LedgerExists`. 048 must not clobber an existing ledger, and
the proper three-way behaviour points to `migrate`, which is 050's.

### 049: the schema check

Production changes:

- `kohle/infrastructure/infra_errors.py`: `NoLedger`, `LedgerBehind`,
  `LedgerAhead`, `LedgerUnreadable`.
- `kohle/db/schema.py`: `HEAD_REVISION` (the 048 revision), `check_schema` and
  `open_ledger`.
- `kohle/app/cli/cli.py`: `_LedgerCommand` and `_KohleGroup`. Delete the group
  callback body. Add `cls=click.Command` to `init`.
- `kohle/app/tui/tui.py`: `open_ledger` (§12).

Tests:

- `tests/test_schema_check.py` (new), §18.3.

README: as in §13.

**Note:** `LedgerBehind` names `kohle-cli migrate` one slice before it exists.
That is acceptable inside the feature branch.

### 050: `migrate`

Production changes:

- `kohle/db/schema.py`: `build_ledger(copy_existing=True)` with the backup
  copy, `Migration`, and `migrate_ledger`.
- `kohle/app/cli/cli.py`: `migrate_cmd` with `cls=click.Command`.

Tests:

- `tests/test_migrate.py` (new), §18.4.

README: as in §13.

### 051: `init` on an existing database; failed `init` leaves nothing

Production changes:

- `kohle/use_cases/ledger.py`: the existing-path branch (§8.2).
- `kohle/domain/domain_errors.py`: `SettingDiffers`.
- `kohle/infrastructure/infra_errors.py`: remove `LedgerExists`.
- `kohle/app/cli/cli.py`: the "already initialized" message.

Tests:

- `tests/test_init.py`: additions as in §18.2.

### 052: `set-setting`, audited

Production changes:

- `kohle/app/cli/cli.py`: `set_setting_cmd`.

Tests:

- `tests/test_settings.py`: CLI additions, §18.5.

README: as in §13.

### 053: `net-worth-history` reads the stored Bundesland

Production changes:

- `kohle/domain/domain_errors.py`: `StateNotSet`.
- `kohle/app/cli/cli.py`: `--state` with no default, and the stored-state read
  (§11).

Test edits:

- `tests/test_portfolio_cli.py`: `_SETUP` gains `["set-setting", "state",
  "BY"]`. Rename `test_net_worth_history_defaults_to_last_working_day_in_bavaria`
  to `test_net_worth_history_uses_the_stored_state`.
- `tests/test_price_guards.py`: the setup of
  `test_new_reports_leave_prices_operations_and_groups_untouched` gains the
  same `set-setting`.

New tests:

- On an unset ledger, plain `net-worth-history` exits 1 with `StateNotSet`'s
  message.
- `--state HE` runs on the same ledger.
- A stored `HE` is used when `--state` is absent.

README: as in §13.

These are existing tests whose behaviour the spec changes on purpose, since
the hidden `BY` default goes. The 053 commit should say so.

---

## 17. Gaps in the spec, and points for the user

1. **The check covers commands that never touch the ledger**, such as
   `list-importer-plugins`. This follows the spec's "every command"
   literally. Exempting it would be a one-word `cls=click.Command` if wanted.
2. **`net-worth-history --period-end month-end` refuses on a ledger without a
   state**, even though the state is ignored in month-end mode. This is the
   spec's unconditional "refuses". Only migrated old ledgers hit it, once. The
   alternative is to require the state only for `last-working-day`.
3. **A re-run of `init` against an old ledger with `state` unset** exits 1 and
   suggests `set-setting state <file's value>`, as the spec says ("unset …
   points to the setter").
4. **A hidden `.kohle.db.XXXX.tmp`** (and possibly `-journal`) can remain in
   the data directory after a hard kill of `init` or `migrate`. It is never
   read. Cleaning it up automatically would mean pattern-deleting siblings
   that a concurrent run might own, so this design does not.
5. **`migrate` and `init` leave the ledger 0600** (`mkstemp`), including
   changing an existing 0644 ledger on `migrate`.
6. **`HEAD_REVISION` is a manual bump per migration.** A test enforces it, and
   a stale value is only slower, never wrong.
7. **`alembic upgrade head` from the repo still upgrades in place**, without
   staging. It is a developer tool, and the README sends users to
   `kohle-cli migrate`.
8. **Two simultaneous `init`s** can clobber each other's fresh ledger (§14,
   Concurrency).
9. **`set-setting` with the current value records no `Operation`**, as with
   `set-price-source`'s identical rebind.
10. **State codes are case-sensitive** (`set-setting state by` is invalid), to
    match `--state`.
11. **`kohle-tui` cannot start** (missing imports, §12). Its new `open_ledger`
    call is verified by review only. For `tui-wiring`: a long-running TUI
    keeps the inode it opened, so a `migrate` in another terminal replaces the
    file under it. The TUI should re-open after a migrate, or the migrate
    should be done with the TUI closed.
12. **For `device-topology-and-sync`:**
    - A reader opened with `mode=ro` cannot roll back a hot journal, so
      snapshots must be taken whole, for example with the backup API
      `build_ledger` already uses, never copied mid-write.
    - The reader marker cannot be a setting; the spec records that already.
13. **The existing ledger at the repo root** is at revision `d4e7a8c15b92`, so
    are its `.bak` files. After the README's move, any command reports "behind;
    run `kohle-cli migrate`", and after `migrate` it needs `set-setting state`.
    There is also a stray `kohle/app/tui/widgets/kohle.db` from a run in that
    directory, the bug this feature removes. The user deletes it by hand.

---

## 18. Testing notes

### 18.1 Isolation (047)

The autouse fixture `_no_real_user_paths` in `tests/conftest.py` sets:

- `KOHLE_DB` to `tmp_path / "no-ledger" / "kohle.db"`, which does not exist;
- `XDG_DATA_HOME` and `XDG_CONFIG_HOME` to temp directories.

Any test that forgets to inject a factory then gets `no ledger at …`, or the
missing-`init.rc` error, instead of touching the real per-user files. Tests of
the fallback order `delenv` and `setenv` what they need, including `HOME`.

A shared fixture from 048 writes `$XDG_CONFIG_HOME/kohle/init.rc` with given
content and points `KOHLE_DB` at a fresh path. A second one runs `init` through
`CliRunner` (no `obj`) and returns the path.

### 18.2 `init` (048, 051)

048, the spec's testable cases:

- With `state = "BW"`: `init`, then `list-accounts` shows `People`, and
  `list-settings` shows `state = BW`, the `KOHLE_DB` path and the revision.
  The revision equals `ScriptDirectory.from_config(alembic_config())
  .get_current_head()`.
- No `init.rc`: exit 1, the message contains `<XDG_CONFIG_HOME>/kohle/init.rc`,
  and nothing exists at `KOHLE_DB`.
- `state = "XX"`, an extra `foo = 1`, no `state` key, and invalid TOML: each
  exits 1 with its message, and nothing exists at `KOHLE_DB` or its parent
  directory.
- The settings write is audited: after `init`, `list-operations` shows one
  `settings` `create` in group 1.
- `init` works with `monkeypatch.chdir(tmp_path)`, from outside the checkout.

051 additions:

- **At head with the same state:** "already initialized at <path>, revision
  <rev>", exit 0, file bytes and mtime unchanged.
- **Behind:** build the ledger with `command.upgrade(alembic_config(),
  "d4e7a8c15b92")` through the dev branch. Expect exit 1, `migrate` in the
  message, and the file unchanged.
- **At head with a different or unset state:** exit 1, `set-setting state BW`
  in the message, and the file unchanged.
- **The file is checked before the database:** an invalid `init.rc` against an
  existing ledger gives the same message as with no ledger.
- **Failure leaves nothing.** Monkeypatch `SetSettings.execute` to return
  `Err` in one test and to raise `KeyboardInterrupt` in another. In both,
  nothing exists at `KOHLE_DB` and no `.kohle.db.*.tmp` is left in the
  directory.
- **A migration refusal is reported cleanly.** Monkeypatch the upgrade to
  raise `RuntimeError` and expect `LedgerBuildFailed`'s message, with no
  traceback.

### 18.3 The check (049)

- **`HEAD_REVISION` is pinned:** it equals `ScriptDirectory` head.
- **Missing:** `list-accounts` with `KOHLE_DB` at a missing path prints the
  spec's line and exits 1. Neither the file nor its parent directory exists
  afterwards.
- **Behind:** a ledger upgraded only to `d4e7a8c15b92` gives the `migrate`
  line, and so does a write command such as `add-account`.
- **Ahead:** `UPDATE alembic_version SET version_num = 'ffffffffffff'` gives
  the upgrade line.
- **Every case prints exactly one line with no `Traceback`**, through
  `CliRunner` and `result.output`.
- **The spec's `mode=ro` case:** `check_schema(path,
  create_engine(f"sqlite:///file:{path}?mode=ro&uri=true"))` is `Ok(head)`, and
  `ListSettings(make_session_factory(make_engine(ro_url))()).execute()`
  succeeds.
- **`--help` needs no ledger:** `list-accounts --help` and `--help` exit 0
  with no ledger, and create nothing.
- **The check does not write:** after the check on a current ledger, file
  bytes and mtime are unchanged.
- **Recommended guard:** in a subprocess, `CliRunner().invoke(cli,
  ["list-accounts"])` on a current ledger leaves `"alembic" not in
  sys.modules`. A stray top-level Alembic import in `schema.py` or
  `ledger.py` would silently add 0.2 s to every command.

### 18.4 `migrate` (050)

- **Behind to head:** start from a ledger built to `d4e7a8c15b92` with an
  account inserted. Expect exit 0, the message names both revisions, the
  account is still there, `settings` exists, and `state` is unset.
- **At head:** "already at", exit 0.
- **No file:** exit 1, `init` named, nothing created.
- **Ahead:** exit 1, "upgrade kohle", file unchanged.
- **Failure:** monkeypatch the upgrade to raise `RuntimeError`. Expect exit 1,
  and the ledger's bytes and revision unchanged.
- **Symlinked ledger:** `KOHLE_DB` is a link to a ledger elsewhere. After
  `migrate` the link is still a link and its target is at head.

### 18.5 `set-setting` (052)

- `set-setting state HE` exits 0, and `list-settings` then shows `state = HE`.
- `list-operations` shows a `settings` `create`. A second, different value
  shows an `update` in a new group.
- **An identical value** adds no `OperationGroup`; count before and after, as
  the read-only guard does.
- **An unknown key or an invalid value** exits 1. The message lists the known
  keys or the 16 codes, and `Setting`, `Operation` and `OperationGroup` counts
  are unchanged.
- These run with an injected `session_factory`, as the existing CLI tests do.
  `create_all` already includes `settings` once the model exists.
