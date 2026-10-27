# Design: Device topology and sync

Spec: `dev/specs/device-topology-and-sync.md` (frozen; its move out of
`dev/inbox/` is not yet committed in the working tree)
Issues: `dev/issues/059`–`063`
Precedents: `dev/design/app-initialization.md` (cited as AI §n) and
`dev/design/device-config.md` (cited as DC §n). AI gave the `mode=rw` URL,
`check_schema(path, engine)` and the staged-file build. DC gave the
`DEVICE_KEYS` registry and the `_KohleCommand` hook. This design extends each
of them and adds no parallel structure.

**Scope, as decided with the user before this design:**

- **Built:**
  - `snapshot <path>`, using `VACUUM INTO` (059);
  - the `ledger.mode` device key, which opens the ledger with `mode=ro` (060);
  - an up-front refusal of write commands on a reader (061);
  - an explicit busy timeout on ledger connections (062);
  - the docs (063).
- **Deferred, and not designed here:**
  - the inbox layout;
  - inotify or SSH-driven imports;
  - `backup`;
  - a phone or tablet reader;
  - the choice between Syncthing and `rsync`;
  - the ESP32 summary file.
- **Topology-neutral.** kohle assumes no Raspberry Pi, no Syncthing, no cron
  and no transport.
  - `ledger.mode = "reader"` is a per-device guard meaning "this device must
    not write this ledger file". kohle enforces no topology.
  - The default is `writer`, so a single-machine user sees no change.
- **The one-writer rule comes from copying a file between devices, not from
  kohle.** Two later options are named in the docs but not built:
  - a server layer in front of SQLite (rqlite, LiteFS, libSQL);
  - a synced operation log, which is a separate and larger feature.
- **No backend interface and no abstraction layer.** The SQLite-specific
  code stays in `kohle/db/connection.py` and `kohle/db/schema.py`, so the one
  connection seam stays easy to replace. That code is:
  - the `mode=ro` URL;
  - `VACUUM INTO`;
  - the busy timeout, and recognising a busy error.

Layering stays as `AGENTS.md` describes it: `app -> use_cases -> services ->
infrastructure/domain`, with `kohle/db/` counting as infrastructure. Functions
return `Result[T, E]`. Error classes are `Exception` subclasses used as
values.

The open point the user left to design, how write commands are identified
(061), is settled in §2. That section also covers how the answer interacts
with the read-only report guard (039) and the schema check (049). Picks the
issues do not pin down are listed in §10 for the user to confirm.

Every "checked" below was run in the scratchpad against this venv: Python
3.12.3, SQLite 3.45.1 and SQLAlchemy 2.0.46.

---

## 1. Summary of the shape

| File | Change | Issue |
|---|---|---|
| `kohle/db/schema.py` | 059: `_open_checked`, `snapshot_ledger`; the module docstring widens to the ledger file's lifecycle. 060: these functions and `open_ledger` take the mode. 062: `check_schema` and `snapshot_ledger` turn a busy error into `LedgerBusy`. | 059, 060, 062 |
| `kohle/db/connection.py` | 060: `ledger_mode(config)`, `ledger_url(path, mode)`. 062: `BUSY_TIMEOUT_SECONDS`, which `make_engine` sets, and `is_busy(error)`. | 060, 062 |
| `kohle/infrastructure/device_config.py` | 060: `LedgerMode`, `LEDGER_MODES`, `_ledger_mode_value`, and the `ledger.mode` entry in `DEVICE_KEYS`. | 060 |
| `kohle/infrastructure/infra_errors.py` | 059: `SnapshotExists`, `SnapshotFailed`. 060: `NoLedger(path, mode)`. 062: `LedgerBusy`. | 059, 060, 062 |
| `kohle/domain/domain_errors.py` | 061: `DeviceIsReader`. | 061 |
| `kohle/infrastructure/transaction_context.py`, `kohle/infrastructure/uow.py` | 062: a busy failure becomes `LedgerBusy` at the two existing seams. | 062 |
| `kohle/use_cases/ledger.py` | 060: `ledger_url(path, "writer")`. | 060 |
| `kohle/app/cli/cli.py` | 059: `snapshot_cmd`. 060: the hook and `snapshot_cmd` pass the mode. 061: `_KohleCommand(writes=...)` becomes required, the refusal goes into `invoke`, and every decorator declares `writes`. | 059–061 |
| `kohle/app/tui/tui.py`, `kohle/app/tui/widgets/table_editor/table_editor.py` | 060: `open_ledger(ledger_path(config), ledger_mode(config))`. | 060 |
| `kohle/db/migrations/env.py` | 060: the URL carries the device's mode. | 060 |
| `tests/test_snapshot.py`, `tests/test_reader.py`, `tests/test_busy.py` | **new** (§9). | 059–062 |
| `tests/test_config_commands.py`, `tests/test_device_config.py` | 060: exact outputs gain `ledger.mode` (§9). | 060 |
| `README.md` | 059–062: short entries. 063: a "Several devices" section (§6). | 059–063 |

No dependency changes. `uv.lock` is untouched.

---

## 2. Decision: how write commands are identified (061)

### 2.1 One guard, in the hook, driven by a declaration every command must make

```python
class _KohleCommand(click.Command):
    def __init__(self, *args, writes: bool, opens_ledger: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.writes = writes
        self.opens_ledger = opens_ledger

    def invoke(self, ctx: click.Context) -> object:
        loaded = load_device_config()
        if loaded.is_err:
            raise click.ClickException(str(loaded.unwrap_err()))
        config = loaded.unwrap()
        ctx.meta[_DEVICE_CONFIG] = config
        mode = ledger_mode(config)
        if self.writes and mode == "reader":
            raise click.ClickException(str(DeviceIsReader(config.path)))
        if self.opens_ledger and ctx.obj is None:
            opened = open_ledger(ledger_path(config), mode)
            if opened.is_err:
                raise click.ClickException(str(opened.unwrap_err()))
            ctx.obj = opened.unwrap()
        return super().invoke(ctx)
```

```python
@cli.command(writes=True)
@click.argument("name")
...
def add_account_cmd(...): ...

@cli.command(name="init", opens_ledger=False, writes=True)
```

**`writes` is a required keyword-only argument.** A `@cli.command()` that
omits it raises `TypeError` when `cli.py` is imported, so every test fails at
once. Click passes the extra keyword arguments through to `command_class`, as
it already does for `opens_ledger` (DC §7.1).

**Why the guard is in the hook:**

- **The hook already runs for every command**, after `--help` parsing and
  after the config is loaded (DC §7.1). The refusal needs the config, and the
  hook is holding it.
- **"Up front" means before the body.** The refusal has to come before any
  plugin, network call, init-file read or engine.
  - `fetch-prices` calls the price plugins before it writes. The free Alpha
    Vantage quota is 25 calls a day.
  - `import-statement` parses the statement before it writes.
  - A refusal at write time would come after both.
- **For `init` and `migrate`, the refusal is the only protection.** Neither
  opens the ledger through the reader's `mode=ro` engine. They build a staged
  file and `os.replace` it onto the path (AI §5.5). On a reader, `mode=ro`
  would not stop `migrate` from replacing the synced copy. For these two
  commands, 061 is the guarantee itself, not a nicer message.

**Why each command carries its own declaration:**

- **Whether a command writes is a fact about the command.** It is not a
  fact about any one use case: `fetch-prices` composes a read
  (`ListPriceTargets`) and a write (`AppendPrices`). Declaring it beside the
  command keeps the fact next to the code it describes.
- **Any default fails silently in one direction:**
  - A default of `False` means a new write command whose author forgot the
    flag runs its plugins on a reader, then hits SQLite's raw "attempt to
    write a readonly database".
  - A default of `True` means a new read command whose author forgot the flag
    is refused on every reader. That is found only when someone uses it on a
    reader, possibly away from home.
  - Neither mistake shows on a writer, which is where development happens.
  - A required argument makes the mistake impossible.
- **The cost is that all 35 decorators gain `writes=` in 061.** That is a
  one-time change. Afterwards each command's access can be read where the
  command is declared.

### 2.2 The classification

| `writes=True` (16) | `writes=False` (19) |
|---|---|
| `init`, `migrate`, `set-setting`, `add-account`, `add-unit`, `import-statement`, `record`, `record-split`, `add-rule`, `remove-rule`, `reclassify`, `add-group`, `split-line`, `unsplit-line`, `set-price-source`, `fetch-prices` | `list-config`, `get-config`, `snapshot`, `list-settings`, `list-accounts`, `list-child-accounts`, `list-units`, `list-importer-plugins`, `entries-in-period`, `balance`, `list-operations`, `list-rules`, `list-unclassified`, `who-owes-what`, `net-worth`, `positions`, `realised`, `settle-up`, `net-worth-history` |

- **`settle-up` is a read.** Its use case says so ("A pure read … writing
  nothing"). It prints `record` lines for the user to run.
- **`snapshot` is a read.** It reads the ledger and writes only its
  destination (§4.1). A reader may copy its own copy.

### 2.3 Order inside `invoke`, and the schema check (049)

The steps run in this order:

1. Load the config (DC).
2. Refuse a write command on a reader.
3. Open the ledger and check its schema, for `opens_ledger` commands.
4. Run the body.

- **The refusal comes before the check.** On a reader, a write command
  answers "reader" even when the ledger is missing or behind.
  - That is the more basic answer: with a perfect ledger the command would
    still be refused.
  - `init` and `migrate` skip the check, so putting the refusal first gives
    every command the same order.
- **The check itself does not change.** It runs on the reader's `mode=ro`
  engine, which 049's own testable case already covers (`check_schema`
  against a `mode=ro` URL).
- **An injected factory is refused too,** because the refusal comes before the
  `ctx.obj` test. Tests drive it through `CliRunner(..., obj=factory)` with a
  reader `config.toml`.
- **`--help` and usage errors come first.** Click exits in `make_context`,
  before `invoke`. So a reader still gets help, and `record` with missing
  arguments is a usage error (exit 2), not the reader message (§10 item 8).

### 2.4 The read-only report guard (039)

- **039 stays as it is.** Its tests check, on a writer, that the report
  commands reference no price writer by identifier and leave the `prices`,
  `Operation` and `OperationGroup` counts unchanged.
- **This feature adds a second, independent guard.**
  - The five report commands (`balance`, `net-worth`, `positions`,
    `realised`, `net-worth-history`) are `writes=False`.
  - On a reader they run on a `mode=ro` engine. A report that wrote anything
    would fail there outright.
  - 039 catches a price writer at the identifier level, on any device. The
    reader test (§9, 061) catches any write at all, at the SQLite level.
- **New structural assertion.** The 039 report set is a subset of the
  `writes=False` commands. A future change that made a report fetch prices
  would have to declare it `writes=True`, and this assertion fails. Reversing
  039 now trips two guards.
- **New behavioural test.** Every `writes=False` command runs, exit 0,
  against a reader snapshot. It is table-driven, with a structural check that
  the table covers exactly the `writes=False` commands. So a new read command
  joins the reader test, or the suite fails.

### 2.5 What is deliberately not done

- **No write detection at the session factory or on flush** (§8).
- **No pretty message for SQLite's readonly error.** On a reader, that error
  can only come from a command wrongly declared `writes=False`. A pleasant
  message would hide the bug, and the reader test finds it before release
  (§10 item 10).

### 2.6 The message (`kohle/domain/domain_errors.py`)

| Class | Fields | Message |
|---|---|---|
| `DeviceIsReader(DeviceConfigError)` | `config_path` | `` this device is configured as a reader; `ledger.mode` is set in {config_path} `` |

```
Error: this device is configured as a reader; `ledger.mode` is set in /home/hari/.config/kohle/config.toml
```

- **It meets 061's wording:** "this device is configured as a reader", plus
  the config file path to edit.
- **It names no transport, tool or schedule.** It also names the key, so the
  user knows what to look for in the file.
- **It does not tell the user to switch to `writer`.** On a device holding a
  synced copy, switching is the wrong move. The docs say when switching is
  right (§6).
- **It has a `DeviceConfigError` base and backticks,** like
  `DeviceKeyNotASetting` (DC §5).
- **The path is always the file that was read.** Only the file can set
  `reader`, because the default is `writer`. So the message never names a
  file that was not found.

---

## 3. `ledger.mode` (060)

### 3.1 The device key (`kohle/infrastructure/device_config.py`)

```python
LedgerMode = Literal["writer", "reader"]
LEDGER_MODES: tuple[LedgerMode, ...] = ("writer", "reader")


def _ledger_mode_value(value: object) -> Result[object, InvalidDeviceValue]:
    if isinstance(value, str) and value in LEDGER_MODES:
        return Result.ok(value)
    return Result.err(InvalidDeviceValue("ledger.mode", value, f"one of {', '.join(LEDGER_MODES)}"))


DEVICE_KEYS: dict[str, DeviceKey] = {
    "ledger.path": DeviceKey(_ledger_path_value, _default_ledger_path),
    "ledger.mode": DeviceKey(_ledger_mode_value, lambda: "writer"),
}
```

**It follows DC §11's contract for new keys:**

- the validator checks form only and does no I/O;
- the default is a callable;
- `str()` renders the value as it is written in TOML;
- there is no environment override, so `KOHLE_DB` stays the only one.

**How it behaves:**

- **Case-sensitive**, as the state codes are. `"Reader"` is invalid.
- **`[ledger]` with `path` and `mode` under it works with no change.**
  `_flatten` already yields both dotted keys.
- **An invalid value stops every command except `--help`**, through the
  existing loader (056). The message is
  `invalid ledger.mode 'Reader'; expected one of writer, reader`, prefixed
  with the file.
- **`list-config` and `get-config` need no code change:**

```
$ kohle-cli list-config
ledger.path = /home/hari/Sync/kohle/kohle.db  (file)
ledger.mode = reader  (file)

file: /home/hari/.config/kohle/config.toml
```

**The default is `writer`, by the user's decision.** The device-config spec
handed this feature a warning: a reader whose `config.toml` disappears falls
back to the default and opens its copy read-write. That risk is accepted.
The backstops sit outside kohle, and the docs state them (§6):

- `config.toml` is a per-device file and must not live in a synced folder;
- one-way sync, which flags or reverts local changes;
- a `chmod 444` copy.

### 3.2 The URL (`kohle/db/connection.py`)

```python
def ledger_mode(config: DeviceConfig) -> LedgerMode:
    return cast(LedgerMode, effective(config, "ledger.mode").value)


def ledger_url(path: Path, mode: LedgerMode) -> str:
    # Neither mode creates a file, so no command can leave an empty kohle.db
    # behind; mode=ro also refuses every write. Quoted because SQLite URIs
    # give '?', '#' and '%' meaning, and an unquoted '?' in a directory name
    # silently opens a different file.
    sqlite_mode = "ro" if mode == "reader" else "rw"
    return f"sqlite:///file:{quote(str(path))}?mode={sqlite_mode}&uri=true"
```

- **`ledger_mode` mirrors `ledger_path`.** It is the typed accessor its
  callers use: the CLI hook, `snapshot_cmd`, the TUI and `env.py`.
- **`mode` is required, so every call site states it.**
  - The device's mode is passed by `open_ledger` (and so the hook and the
    TUI), `snapshot_ledger` and `env.py`.
  - `"writer"` is passed by `migrate_ledger`, `build_ledger`'s populate
    engine, `_upgrade_to_head` and `init_ledger`'s `_compare_existing`.
    Either the file is kohle's own staged file, or the command is refused on
    a reader before it runs (§2.1).
- **The device's vocabulary crosses into `connection.py` on purpose.**
  Turning "reader" into a way of opening the database is this seam's job. A
  later layer in place of SQLite would map `reader` to its own read-only
  access, and nothing above the seam would change.
- **Checked:**
  - a write on a `mode=ro` engine fails with `SQLITE_READONLY`, "attempt to
    write a readonly database";
  - `mode=ro` on a missing path fails with `SQLITE_CANTOPEN`, "unable to
    open database file", and creates nothing;
  - the foreign-key pragma works on `mode=ro` (AI §4.2).

### 3.3 Opening (`kohle/db/schema.py`)

```python
def _open_checked(path: Path, mode: LedgerMode) -> Result[Engine, LedgerError]:
    if not path.exists():
        return Result.err(NoLedger(path, mode))
    engine = make_engine(ledger_url(path, mode))
    return check_schema(path, engine).map(lambda _: engine)


def open_ledger(path: Path, mode: LedgerMode) -> Result[sessionmaker[Session], LedgerError]:
    return _open_checked(path, mode).map(make_session_factory)
```

**`_open_checked` comes in with 059,** without the mode, because `snapshot`
needs an engine where `open_ledger` returns a session factory (§4.2).
`open_ledger` keeps its result type, so the hook, the TUI and the tests that
monkeypatch it are unaffected.

**A reader's copy can hit four states other than "current":**

- **Ahead of this kohle** (a copy from a newer writer): `LedgerAhead`, "upgrade
  kohle". That is the right advice on a reader.
- **Behind this kohle:** `LedgerBehind` says to run `migrate`, which the
  reader refuses (§10 item 3).
- **A hot journal:** a `mode=ro` connection cannot roll one back (AI §4.2), so
  it reports `LedgerUnreadable`.
  - A snapshot never has a hot journal.
  - A reader pointed at a live file that another process writes could hit
    it. The docs tell readers to open a snapshot.
- **A WAL-mode source:** this never reaches a reader.
  - Checked: `VACUUM INTO` from a WAL-mode source writes a rollback-journal
    file (header bytes 18–19 are `1, 1`).
  - `mode=ro` reads that file with no side files.
  - This confirms the spec's claim that the writer's journal mode does not
    matter to readers.

### 3.4 A missing file on a reader

```python
class NoLedger(LedgerError):
    def __init__(self, path: Path, mode: LedgerMode):
        ...

    def __str__(self) -> str:
        if self.mode == "reader":
            return f"no ledger at {self.path}; this device is configured as a reader and never creates one"
        return f"no ledger at {self.path}; run `kohle-cli init`"
```

- **Issue 060 asks for "unable to open database file" semantics.** The
  command fails loudly and creates nothing.
  - `path.exists()` gives the message.
  - `mode=ro` guarantees that even a file vanishing between the two calls
    creates nothing.
- **The init hint is dropped on a reader, for a reason.**
  - The writer wording sends the user to `init`, which the reader refuses.
  - The obvious next move is to switch to `writer` and run `init`. That
    creates an empty ledger where the copy should arrive: the "wrong path
    shows an empty ledger" outcome that the spec's second layer exists to
    prevent.
- **The writer wording is unchanged,** so 049's tests keep passing.
  `migrate_ledger` passes `"writer"`.
- **`infra_errors.py` imports `LedgerMode` from `device_config.py`.** There is
  no cycle: `device_config` imports only `kohle.core.result` and
  `kohle.domain.domain_errors`, and neither imports `infra_errors`.

### 3.5 The TUI and `env.py`

**`tui.py`'s `main()` and the `table_editor.py` demo** call
`open_ledger(ledger_path(config), ledger_mode(config))`.

- The TUI gets a `mode=ro` engine on a reader.
- It has no up-front refusal of its own write actions, because `writes` is a
  Click concept. `tui-wiring` must add one. Until then, SQLite's refusal
  protects the file.

**In `env.py`, `_ledger()` becomes `_ledger_url()`.** It returns
`ledger_url(ledger_path(config), ledger_mode(config))`, and both branches use
it.

- This keeps 055's "kohle-cli, kohle-tui and the Alembic environment resolve
  the ledger the same way".
- On a reader, `alembic upgrade` fails with SQLite's readonly error.
  `alembic revision --autogenerate` only reads, and works.
- `env.py` is a developer tool, so it gets no up-front refusal (§10 item 9).

---

## 4. `snapshot <path>` (059)

### 4.1 The command (`kohle/app/cli/cli.py`)

```python
@cli.command(opens_ledger=False, writes=False)
@click.argument("dest", type=click.Path(path_type=Path))
@pass_device_config
def snapshot_cmd(config: DeviceConfig, dest: Path) -> None:
    path = ledger_path(config)
    res = snapshot_ledger(path, ledger_mode(config), dest)
    if res.is_err:
        raise click.ClickException(str(res.unwrap_err()))
    click.echo(f"Wrote a snapshot of {path} to {dest}")
```

- **`opens_ledger=False`, like `init` and `migrate`.**
  - The command hands the path to `kohle/db`, which opens the ledger itself.
    It needs an engine, not a session factory.
  - With this third user, the flag's meaning is: the hook does not open the
    ledger, because the command either needs none (`list-config`,
    `get-config`) or opens it through `kohle/db` (`init`, `migrate`,
    `snapshot`).
  - `_KohleCommand`'s docstring says so.
  - A snapshot still gets the missing-ledger and schema checks, through
    `_open_checked`.
- **`writes=False`.**
  - The command never writes the ledger.
  - It is allowed on a reader. Checked: `VACUUM INTO` works on a `mode=ro`
    connection.
- **`DEST` is any path:**
  - relative paths are taken from the working directory;
  - there is no fixed location;
  - Click checks nothing, so every refusal comes through the one message in
    §4.3.
- **The CLI never sees SQLite.** It knows paths and `Result`s only.

### 4.2 `snapshot_ledger(path, mode, dest)` (`kohle/db/schema.py`)

```python
def snapshot_ledger(path: Path, mode: LedgerMode, dest: Path) -> Result[Path, LedgerError]:
    """Write a consistent, self-contained copy of the ledger to `dest`, which
    must not exist. Reads the ledger only."""
    opened = _open_checked(path, mode)
    if opened.is_err:
        return Result.err(opened.unwrap_err())
    engine = opened.unwrap()
    staged: Path | None = None
    try:
        # A symlink, dangling or not, is an existing path; os.replace would
        # replace the link.
        if dest.exists(follow_symlinks=False):
            return Result.err(SnapshotExists(dest))
        # Beside dest so the rename is atomic: whatever watches dest sees no
        # file or a whole snapshot, never a half-written one.
        fd, name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp")
        os.close(fd)
        staged = Path(name)
        with engine.connect() as connection:
            connection.exec_driver_sql("VACUUM INTO ?", (str(staged),))
        # VACUUM INTO does not fsync its output; without this a power cut
        # after the rename can leave a torn file at dest.
        fd = os.open(staged, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(staged, dest)
        return Result.ok(dest)
    except DBAPIError as e:
        return Result.err(SnapshotFailed(dest, str(e.orig)))  # 062: LedgerBusy when busy
    except OSError as e:
        return Result.err(SnapshotFailed(dest, e.strerror or str(e)))
    finally:
        engine.dispose()
        if staged is not None:
            staged.unlink(missing_ok=True)
```

**The steps:**

1. **The ledger comes first, as with every command (049).** A missing ledger
   gives `NoLedger` and nothing is created. A ledger that is behind or ahead
   is refused.
2. **An existing `dest` is refused in any form:** a file, an empty file, a
   directory or a symlink.
   - Checked: `VACUUM INTO` itself refuses a non-empty file ("output file
     already exists") but accepts an empty one. The refusal is therefore
     kohle's own check, not SQLite's.
3. **Stage beside `dest`.**
   - `mkstemp` makes a 0-byte file, which `VACUUM INTO` accepts (checked).
   - That is the same idiom as `build_ledger` (AI §5.5).
4. **Run `VACUUM INTO` with a bound parameter.**
   - It is one read transaction, so the copy is consistent even while
     another process writes. A writer's commit waits for it, or it waits for
     the commit (§5).
   - Checked: `exec_driver_sql("VACUUM INTO ?", …)` works on `mode=rw` and
     `mode=ro` engines.
   - The staged name never starts with `file:`, so SQLite never reads it as a
     URI.
5. **`fsync` the staged file.** SQLite's documentation of `VACUUM INTO` says
   it does not sync its output. The Pi in the spec runs from an SD card and
   can lose power.
6. **`os.replace`** publishes the file.
7. **In `finally`,** remove the staged file and dispose of the engine. After
   a successful replace the staged name no longer exists, so the unlink does
   nothing.

**The properties that follow:**

- **No side file is left beside `dest`.** Checked: there is no `-journal`,
  `-wal` or `-shm` beside the output, and the staged file is renamed or
  removed.
- **The live ledger is only read.** No `Operation` and no `OperationGroup` is
  written, and its bytes and mtime do not change.
- **The snapshot opens as an ordinary ledger.** It is a complete SQLite file
  at the same revision, `alembic_version` included.
- **The file is 0600**, from `mkstemp`, the same as ledgers built by `init` and
  `migrate`. `chmod 444` is the user's backstop, and the docs say so.
- **The parent directory must exist.** A mistyped destination fails instead
  of leaving directories behind (§10 item 7).
- **A hard kill can leave `.<name>.XXXX.tmp` beside `dest`.** kohle never reads
  it, and it is safe to delete. A sync tool watching the folder may carry it.

### 4.3 Errors (`kohle/infrastructure/infra_errors.py`)

| Class | Fields | Message |
|---|---|---|
| `SnapshotExists(LedgerError)` | `dest` | `{dest} already exists; snapshot never overwrites a file` |
| `SnapshotFailed(LedgerError)` | `dest, reason` | `writing a snapshot to {dest} failed: {reason}` |

- **They sit beside `LedgerBuildFailed`.** They describe what happened to the
  ledger file's copy.
- **A missing parent directory** reads
  `writing a snapshot to /x/y.db failed: No such file or directory`.

### 4.4 Why the code lives in `schema.py`

- **It shares two things already there:** `_open_checked`, and the staging
  idiom of `build_ledger`, which already holds `_copy_ledger`'s backup-API
  copy.
- **The module docstring widens** from "Schema lifecycle for the ledger" to
  "The ledger file's lifecycle: opening and checking it, building and
  migrating it, and copying it". The note about the lazy Alembic import stays.
- **A one-function `kohle/db/snapshot.py` would be a parallel structure.** It
  would also have to import `_open_checked` back from `schema.py`.

This is where 059's "the SQLite-specific code sits with the connection code"
is met: `VACUUM INTO` appears nowhere outside `kohle/db/`, and a structural
test proves it (§9).

---

## 5. The busy timeout (062)

### 5.1 What happens today

Checked: Python's `sqlite3` gives every connection a 5 s busy timeout by
default. `PRAGMA busy_timeout` reads `5000` through `make_engine`.

- **A second writer therefore already waits 5 s.** It then fails with
  SQLAlchemy's multi-line `(sqlite3.OperationalError) database is locked
  [SQL: …]`, which a service passes through as text.
- **062 changes two things.** The wait becomes an explicit, longer value that
  kohle owns, and the raw message is replaced.

### 5.2 The timeout (`kohle/db/connection.py`)

```python
# A kohle write transaction is short: plugins and network calls run before it
# opens, and the ledger is a few hundred KB. 30 s outlasts any of them on a
# Raspberry Pi 3, and is short enough that a lock held by a stuck process
# surfaces while someone is still waiting on the command.
BUSY_TIMEOUT_SECONDS = 30.0


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"timeout": BUSY_TIMEOUT_SECONDS})
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def is_busy(error: Exception) -> bool:
    # Extended codes such as SQLITE_BUSY_SNAPSHOT share the primary code's low byte.
    return (
        isinstance(error, DBAPIError)
        and isinstance(error.orig, sqlite3.Error)
        and error.orig.sqlite_errorcode & 0xFF == sqlite3.SQLITE_BUSY
    )
```

**How the setting works:**

- **`connect_args={"timeout": ...}` is pysqlite's own busy-timeout
  parameter.** Checked: `PRAGMA busy_timeout` reads `30000`.
- **It is read when `make_engine` is called,** so a test can monkeypatch the
  module attribute.
- **The scale.** The user's ledger backups are 61 KB and 110 KB. A
  `VACUUM INTO` or an import of that size takes milliseconds, even on a Pi.

**Which connections get it.** Issue 062 asks that the timeout not be tied to
any caller, so every engine `make_engine` builds has it:

- the CLI and TUI ledgers, in both modes;
- `migrate`'s check engine;
- `init`'s comparison engine;
- `build_ledger`'s populate engine.

**Readers get it too.** A reader that opens a live file on the same machine
waits for a commit like anyone else. On a snapshot, nothing ever contends.
The issue says "writer connections", but leaving readers out gains nothing
and would need a parameter (§10 item 5).

**Not changed:**

- `_upgrade_to_head`'s engine on the staged file: the file is private, so
  nothing contends.
- `env.py`'s developer engine: Python's 5 s default.
- `_copy_ledger`'s backup-API copy in `migrate`: CPython's backup loop
  retries a locked source with no limit. Checked: it completed after a 7 s
  exclusive hold, despite the 5 s connect timeout (§10 item 6).

**Why the wait works in kohle, and what would break it.** SQLite calls the
busy handler only when the waiting connection holds no read transaction. If
it holds one and wants to write, SQLite returns `SQLITE_BUSY` at once to
avoid a deadlock.

- **In legacy mode, a use case's first write starts from no lock.**
  pysqlite's legacy transaction mode sends `BEGIN` only before the first
  `INSERT`, `UPDATE` or `DELETE`. A use case's reads therefore run outside
  any transaction, which is the case the busy handler covers.
- **Checked:**
  - a read followed by a write waited 1.05 s for a writer that held its lock
    for 1 s;
  - a commit waited 1.05 s for a reader that held its read lock for 1 s.
- **A constraint for later changes.** If reads ever open a transaction first,
  the upgrade to a write fails at once, with no wait. SQLAlchemy's "emit
  `BEGIN` on the `begin` event" recipe, which AI §15 considered for
  migrations, does exactly that. Checked: it failed after 0.00 s with a 30 s
  timeout. Such a change must begin write transactions with
  `BEGIN IMMEDIATE`.

### 5.3 The message

| Class | Fields | Message |
|---|---|---|
| `LedgerBusy(LedgerError)` | | `the ledger stayed locked by another process; nothing was changed, try again` |

- **The message gives no duration.** `SQLITE_BUSY` can also come from the
  deadlock case above, which fails at once, so the message does not claim a
  wait that may not have happened. The README states the 30 s.
- **It is a `LedgerError`.** Like `NoLedger`, it describes the ledger file's
  state, and `check_schema` and `snapshot_ledger` return that family.

**Where a busy error is recognised.** Checked: it can surface at a statement
in a use case and at commit. It can also surface at the per-command check, if
another process holds `EXCLUSIVE`. Each existing seam turns it into
`LedgerBusy`:

| Seam | Today | After |
|---|---|---|
| `DbTransactionContext.run` (a statement or flush) | `InfrastructureError(str(e))`; the service wraps the text | `LedgerBusy() if is_busy(e) else InfrastructureError(str(e))` |
| `DbTransaction.execute` (commit) | `Result.err(e)`, the raw SQLAlchemy error | `LedgerBusy() if is_busy(e) else e` |
| `check_schema` | `LedgerUnreadable(path, "database is locked")` | `LedgerBusy() if is_busy(e) else LedgerUnreadable(...)` |
| `snapshot_ledger` | `SnapshotFailed(dest, "database is locked")` | `LedgerBusy() if is_busy(e) else SnapshotFailed(...)` |

- **The two transaction seams are the broad catches the `AGENTS.md` override
  allows.**
  - They gain one conditional each, and no new `except`.
  - They learn only `is_busy`. The SQLite error code stays in
    `connection.py`.
- **No service changes.** Every service maps its infrastructure error as
  `XError(str(err))`, so `LedgerBusy`'s text reaches the CLI as it is.
  - `check_if_unique_constraint_failed` is unaffected, because `LedgerBusy` is
    not a `UniqueViolation`.
  - `ctx.run`'s annotated error type widens to `InfrastructureError |
    LedgerBusy`.
- **"Nothing was changed" holds.**
  - `UnitOfWork` rolls back on `Err`.
  - A commit that fails with `SQLITE_BUSY` leaves the transaction open, and
    `DbTransaction.execute` rolls it back.
  - `fetch-prices` drops the closes it fetched; a rerun fetches them again.
- **No retry loop.** SQLite's busy handler already retries the lock. A loop
  around the use case would re-run plugins and network calls (§8).

---

## 6. Docs (063)

**Where.** The docs go in a new `README.md` section, `### Several devices`,
placed last, after the plugin sections.

- The README is the user documentation. `docs/` holds design transcripts.
- The quick start ("Running", "First run") never mentions the topic, so a
  single-machine user can skip it.
- The "Device config" key list links to the section from its `ledger.mode`
  entry.
- `cli-documentation` may move the section later.

**The section covers, in order:**

1. **Who can skip it:** one machine, no copies.
2. **The model kohle supports:**
   - one device holds the writable ledger;
   - other devices read a copy;
   - `snapshot` makes the copy;
   - `ledger.mode = "reader"` keeps a copy read-only.
3. **Why one writer.** This is a property of copying a file between devices,
   not of kohle:
   - file sync tools produce conflict copies, not merges, when two devices
     write;
   - network filesystems lock unreliably, so SQLite's lock cannot serialise
     writers across machines.
4. **The other strategies.** This model is option one of the known
   strategies, and it is the one kohle supports.
   - A server layer in front of SQLite (rqlite, LiteFS, libSQL) is a possible
     later option.
   - A synced operation log is a larger, separate feature.
   - Neither is built.
   - The connection is one seam in `kohle/db/`, so another layer could be
     added there later.
5. **Setting up a reader:**
   - `config.toml` with `[ledger]`, `path = "~/Sync/kohle/kohle.db"` and
     `mode = "reader"`;
   - what changes: write commands refuse with the §2.6 message, and reads
     work normally;
   - the missing-file message;
   - what "ahead" means on a reader: upgrade kohle there.
6. **Making and moving copies:**
   - `kohle-cli snapshot <path>`: a consistent copy, no side files, refuses
     an existing path, file mode 0600, a hidden temporary file beside it while
     it is written;
   - because it never overwrites, a scheduled job snapshots to a temporary
     name and renames it over the last copy.
   - Syncthing (Send Only on the writer, Receive Only on readers), a scheduled
     `rsync` pull, cron and a Raspberry Pi appear only as examples. The
     user's own setup is one worked example: a Pi 3 as the writer, a daily
     `fetch-prices` and `snapshot` from cron into a Syncthing folder, and the
     laptop and tablet as readers.

     ```bash
     rm -f ~/Sync/kohle/.kohle.db.new
     kohle-cli snapshot ~/Sync/kohle/.kohle.db.new && mv ~/Sync/kohle/.kohle.db.new ~/Sync/kohle/kohle.db
     ```
7. **Several writers on one machine** (a scheduled fetch and an import, say):
   SQLite serialises them, a writer waits up to 30 s for another, and then it
   fails with the §5.3 message.
8. **Backstops and caveats:**
   - `chmod 444` on a reader's copy also refuses a plain open's write;
   - reader copies are not backups: a corruption on the writer syncs out to
     every reader;
   - keep `config.toml` out of synced folders, because it describes one
     device, and a reader that loses it falls back to `writer`;
   - point readers at a snapshot, not at a live file another process writes.

**Per-slice README edits** follow the precedent of updating as each slice
lands:

| Slice | Edit |
|---|---|
| 059 | `### Snapshots`, at the end: the command, its refusals, the 0600 mode, the hidden temporary file. 063 folds it into "Several devices". |
| 060 | "Device config": the `ledger.mode` key (`writer` default, `reader`), one paragraph on what reader does, and the reader `NoLedger` wording. |
| 061 | One sentence under `ledger.mode`: write commands refuse on a reader before doing anything. |
| 062 | One paragraph in "Schema check" or beside it: concurrent writers on one machine wait up to 30 s, then the message. |
| 063 | The "Several devices" section above. |

**`AGENTS.md`'s Context should gain one sentence after landing.** This design
does not edit it; the user does. Suggested: "A device whose `config.toml`
sets `ledger.mode = "reader"` opens the ledger with SQLite's `mode=ro`, and
every command declared `writes=True` refuses there before it acts. `snapshot`
writes a consistent copy with `VACUUM INTO`. All SQLite-specific connection
code is in `kohle/db/`."

---

## 7. The decision categories

### State and data lifecycle

**`snapshot` is one unit.** `VACUUM INTO` a staged file, then `fsync`, then
`os.replace`.

- At `dest` there is either nothing or a whole snapshot.
- On failure or Ctrl-C, the staged file is removed in `finally`.
- A hard kill can leave a hidden `.tmp`, but never anything at `dest`, so a
  rerun proceeds.

**The source is read in one read transaction,** so the copy is a consistent
point in the ledger's history even while another process writes.

- The live ledger is never modified.
- A snapshot is not a ledger change, so it records no `Operation`.
- It is replayable: run it again to a new path.

**A reader never changes its file.** Two mechanisms together make that hold:

- SQLite's `mode=ro` covers every command that opens the ledger through the
  hook or `_open_checked`.
- The up-front refusal covers `init` and `migrate`, which replace files by
  staging and would bypass `mode=ro` (§2.1).

**The refusal is all-or-nothing and comes first.** No engine, plugin,
network call or init-file read happens before it.

**A busy failure leaves nothing behind.** The `UnitOfWork` rolls the whole
transaction back.

**Nothing new is persisted.** `ledger.mode` lives in a file kohle never
writes (DC). Snapshots are files the user owns. There is no table and no
migration, so `HEAD_REVISION` is unchanged.

**An accepted risk:** a reader that loses `config.toml` falls back to
`writer` (§3.1). The backstops live outside kohle, and the docs state them.

### Error propagation

| From | Caught where | Becomes |
|---|---|---|
| A `writes=True` command on a reader | `_KohleCommand.invoke`, before anything else | `DeviceIsReader` → `ClickException`, exit 1 |
| A missing file on a reader | `_open_checked` | `NoLedger(path, "reader")`, with the reader wording |
| `SQLITE_BUSY` at a statement | `DbTransactionContext.run` | `LedgerBusy` → the service's `XError(str)` → CLI |
| `SQLITE_BUSY` at commit | `DbTransaction.execute` | `LedgerBusy` → CLI |
| `SQLITE_BUSY` in the check | `check_schema` | `LedgerBusy` |
| An existing `dest` | `snapshot_ledger` | `SnapshotExists` |
| `VACUUM INTO` or file failures | `snapshot_ledger`: `except DBAPIError`, `except OSError` | `SnapshotFailed`, or `LedgerBusy` when busy |
| `SQLITE_READONLY` on a reader | `DbTransactionContext.run`, unchanged | Raw text. It means a command was declared `writes=False` wrongly, and the reader test catches that (§2.5). |

**What each layer knows:**

- **`connection.py`** knows the SQLite open modes, how `reader` maps to
  `mode=ro`, the busy timeout, and how to recognise a busy error.
- **`schema.py`** knows opening and checking, `VACUUM INTO`, and staging.
- **The transaction seams** know only `is_busy()` and `LedgerBusy`. They do
  not know SQLite's error codes.
- **The CLI** knows the device mode and each command's `writes` declaration.
  It does not know about `mode=ro`, `VACUUM INTO` or busy errors; it prints
  `str(err)`.
- **Use cases and services learn nothing new.** Reader mode is invisible to
  them.

**No new broad `except`.** The two `AGENTS.md` override seams each gain one
conditional. `snapshot_ledger` catches explicit types.

### Concurrency and ownership

**Each kohle process is single-threaded, with no shared in-process mutable
state.**

- The engine belongs to the Click context (`ctx.obj`) or to the
  `snapshot_ledger` call that made it.
- `DeviceConfig` is frozen, and `DEVICE_KEYS` is a constant.

**Several processes on one machine are what 062 is about.** A scheduled
fetch, an import, a snapshot and an interactive command may overlap.

- SQLite's file locks serialise them, and the 30 s busy timeout turns a clash
  into a wait.
- A snapshot holds a read lock for milliseconds, and a writer's commit waits
  for it.
- A snapshot waits for a writer's commit in the same way.
- The wait relies on pysqlite's legacy transaction mode (§5.2). That is a
  stated constraint, not an accident.

**Across devices, kohle coordinates nothing.**

- One writer per file is the user's topology.
- `ledger.mode = "reader"` only stops this device's kohle from writing its
  copy.
- Copies arrive by the user's transport, which replaces the file by rename.
  A reader mid-command keeps the inode it opened.

**The publish race is accepted.**

- `snapshot` refuses `dest` if it exists at the start, then publishes with
  `os.replace`.
- A file that another process creates at `dest` during the copy would be
  replaced. The window lasts milliseconds for a ledger this size, and only a
  second job writing the same path could hit it.
- Same reasoning as AI's accepted clash between two simultaneous `init`s;
  `os.link` is rejected in §8.

**`migrate`'s backup copy is unchanged.** It still waits without limit on a
locked source (§5.2).

**If this code is reused elsewhere,** say from a threaded TUI: every
function here takes its inputs as arguments and keeps no module state. Each
thread must use its own session, as SQLAlchemy requires anyway.

### Reuse

**What this uses instead of rebuilding:**

- **The `DEVICE_KEYS` registry** (DC §4). `ledger.mode` gets validation, the
  bad-file refusal, `list-config` and `get-config` with no new code.
- **`_KohleCommand.invoke`** (DC §7.1). One new step goes into the hook every
  command already passes through, and the existing structural test that every
  command is a `_KohleCommand` now covers the `writes` declaration too.
- **`check_schema(path, engine)`'s engine parameter**, which AI §5.3 built "so
  reader mode later needs nothing new". It needs nothing.
- **`build_ledger`'s staging idiom** (AI §5.5): `mkstemp` beside the target,
  publish with `os.replace`, unlink in `finally`.
- **The error conventions:** `click.ClickException(str(err))`, and `__str__`
  as the one-line message.
- **Test helpers:** `write_config`, `write_init_rc`, `run_init`, and
  `test_schema_check.py`'s `_build`, `_set_revision` and `BEHIND`.

**What is factored so the next feature can reuse it:**

- **`_open_checked`**, shared by `open_ledger` and `snapshot_ledger`. A later
  `backup` would use it too.
- **`snapshot_ledger`**, the building block for the deferred `backup`
  (snapshot to a dated path).
- **`is_busy`**, for any later seam that meets the lock.
- **The `writes` declaration,** which a later CLI command must make. The TUI
  needs its own equivalent (§3.5).

### Extension points

1. **`writes=` on every CLI command.** The contract:
   - `True` if the command writes the ledger by any route: a use case, a
     staged rebuild, or a file replace;
   - `False` if it only reads the ledger, even if it writes other files
     (`snapshot`);
   - the reader test table must list the command.
2. **`DEVICE_KEYS`** gains `ledger.mode`. Later keys follow DC §11's
   contract.
3. **The connection seam.** A replacement layer (rqlite, LiteFS, libSQL)
   would reimplement these and keep their contracts:
   - `ledger_url` and `make_engine`;
   - `is_busy`;
   - `open_ledger(path, mode)`, which returns a session factory or a
     `LedgerError`;
   - `snapshot_ledger(path, mode, dest)`, which writes a self-contained copy
     or a `LedgerError`.

   `reader` must keep meaning "this device never writes". Nothing above
   `kohle/db/` would change. This is the "single seam" the docs mention, and
   there is no interface type for it: the module functions are the contract.
4. **None for plugins.** Plugins cannot see or change the mode.

### Build vs. buy

| Component | Decision | Evaluated, and why not |
|---|---|---|
| Consistent copy | **Buy**: SQLite's `VACUUM INTO` | Fixed by 059. It is one SQL statement on the engine kohle already opened, so the reader URL and the busy timeout apply unchanged. It writes a compact rollback-journal file from any source journal mode (checked). The backup API, which `_copy_ledger` uses, needs a second raw `sqlite3` connection outside `make_engine`, and its CPython loop waits without limit on a locked source (checked). `shutil.copy` can tear against a concurrent writer (spec). |
| Atomic publish | **Build** on `tempfile.mkstemp` + `os.fsync` + `os.replace` | `os.link` + `unlink` would be a true no-clobber publish, but it fails on filesystems without hard links (FAT and exFAT sticks, some FUSE mounts), while 059 accepts any destination (AI §15, same reason). `atomicwrites`-style libraries write byte streams; they do not help SQLite write a file. |
| Read-only open | **Buy**: SQLite `mode=ro` | Spec layer 2, checked. `immutable=1` was rejected (§8). File permissions are the user's backstop, not kohle's guarantee. |
| Waiting on a lock | **Buy**: SQLite's busy handler, through pysqlite's `timeout` | A retry loop (hand-written, or `tenacity`, which would be a new dependency) would re-run whole use cases, plugins and network calls included. `PRAGMA busy_timeout` in the connect listener is equivalent but needs SQL where the driver takes a parameter. |
| Write-command classification | **Build**: one required flag on the existing Click command class | Click has no notion of command access. A session-level guard comes too late (§8). |
| Multi-device sync | **Neither.** Out of scope; the user's transport. | rqlite, LiteFS and libSQL put a server in front of SQLite; that is a later option (063 docs). Syncthing and `rsync` are the user's choice and appear only as examples. |

### Abstractions introduced

| Abstraction | Forcing problem |
|---|---|
| `ledger.mode` in `DEVICE_KEYS`, `_ledger_mode_value` | 060: a registered key with two valid values, validated like every device value. |
| `LedgerMode`, `LEDGER_MODES` | The validator, `ledger_url`, `NoLedger` and the hook all need the same two values. The `Literal` lets mypy check every comparison, and the tuple gives the validator its list and message. |
| `ledger_mode(config)` | Four callers need the typed mode; it mirrors `ledger_path(config)`. |
| `ledger_url(path, mode)` (required parameter) | 060: the URL must differ by mode, and every call site must state which mode it opens with. |
| `_open_checked(path, mode)` | `open_ledger` and `snapshot_ledger` both need "exists, else `NoLedger`; engine; check". One wants a session factory and the other an engine. |
| `snapshot_ledger(path, mode, dest)` | 059: the SQLite-specific copy must sit with the connection code, behind a path-and-`Result` interface the CLI can call. |
| `SnapshotExists`, `SnapshotFailed` | 059: a clear refusal and a one-line failure. |
| `NoLedger.mode` | 060: on a reader, the `init` hint leads to an empty ledger (§3.4). |
| `_KohleCommand(writes=...)`, required | 061: an up-front refusal needs each command's access, and the declaration must be impossible to forget (§2.1). |
| `DeviceIsReader` | 061: the message. |
| `BUSY_TIMEOUT_SECONDS` | 062: an explicit value kohle owns, settable in tests. |
| `is_busy(error)` | 062: four seams must recognise `SQLITE_BUSY` without knowing SQLite's error codes. |
| `LedgerBusy` | 062: a clear message in place of the raw "database is locked". |

**Not introduced:**

- a backend interface or `Protocol` (the user's decision);
- a `LedgerMode` enum class;
- an `access="none"|"read"|"write"` parameter;
- a `status` command;
- a lock-wait device key;
- a retry helper;
- a `kohle/db/snapshot.py` module;
- a reader-aware `LedgerBehind`, which is a gap (§10 item 3).

---

## 8. Alternatives rejected

- **Write detection at the session factory, or on flush.** A reader factory
  whose sessions refuse to flush, or a `before_flush` listener, was
  considered.
  - It fires only when a write happens, which is after `fetch-prices` has
    spent API calls and after `import-statement` has parsed the file.
  - It never sees `init` or `migrate`, which write through a staged file.
  - Its error would reach the user as text through the broad `except`.
- **A check in each write command's body.** That is 16 call sites, each
  needing `@pass_device_config`. A forgotten one is silent.
- **A `_WRITE_COMMANDS` set in `cli.py` or in a test.** It is a second list
  that drifts from the declarations. The flag puts the fact on the command.
- **`writes` with a default, either way.** Each default fails silently in one
  direction (§2.1).
- **Inferring access from use-case classes.** Commands compose several use
  cases, and `init`, `migrate` and `snapshot` use none.
- **Relying on SQLite's readonly error, with a nicer message.** It is not up
  front, and it does not cover `init` or `migrate`.
- **One `access="none"|"read"|"write"` parameter instead of `opens_ledger`
  and `writes`.** `init` and `migrate` write without the hook opening the
  ledger, so the two questions are independent. Three values cannot express
  all four combinations.
- **The reader marker as a ledger setting.** The AI spec rules it out: the
  next sync would overwrite it.
- **The reader marker as an environment variable.** That is a DC spec
  non-goal.
- **The reader marker as the absence of something only the writer has.** It
  is implicit, and a reader that gains the thing silently becomes a writer.
  The user chose the config key.
- **A default of `reader`.** Every single-machine user would have to
  configure kohle before writing. The user decided on `writer`.
- **`snapshot` through the backup API, or by copying the file.** See Build
  vs. buy.
- **`VACUUM INTO` straight to `dest`.**
  - An interrupted run leaves a torn file at `dest`, which a sync tool may
    distribute and which blocks the rerun.
  - A watcher can also see the file half-written.
- **Overwriting, or a `--force` flag.** 059 says an existing path is refused.
- **`os.link` for a no-clobber publish.** See Build vs. buy.
- **Creating `dest`'s parent directories.** A mistyped path would leave
  directories behind. A missing directory is reported instead.
- **`snapshot` through the hook (`opens_ledger=True`), taking the engine from
  the session factory.** The CLI would have to reach into the factory
  (`sessionmaker.kw["bind"]`) or open a `Session` for `get_bind()`. Both make
  the CLI handle SQLAlchemy objects that only `kohle/db` and services touch.
  The path-based form matches `migrate`.
- **`snapshot` as a use case and service.** It would put `VACUUM INTO` in
  `services/`. 059 asks for it beside the connection code.
- **A separate `kohle/db/snapshot.py`** (§4.4).
- **`snapshot` doing `chmod 444` itself.** No issue asks for it. Read-only
  permissions are the backstop of the user's transport setup, and the docs
  cover them.
- **`immutable=1` in the reader URL.** SQLite would skip locking and change
  detection. A reader on a file that another process writes could read
  inconsistent pages. `mode=ro` keeps normal locking.
- **The busy timeout on writer engines only.** It would need a parameter on
  `make_engine`, and readers on a live file benefit from waiting.
- **A lock-wait device key**, which the device-config spec anticipated. There
  is no evidence that 30 s is wrong for any device. When there is,
  `DEVICE_KEYS` takes the key with nothing else changed.
- **A retry loop around use cases.** See Build vs. buy.
- **SQLAlchemy's `handle_error` event, to rewrite busy errors inside
  `make_engine`.**
  - Raising a non-`DBAPIError` from inside SQLAlchemy would slip past
    `check_schema`'s and `build_ledger`'s `except DBAPIError` as a traceback.
  - Converting at the seams that already turn failures into `Result`s keeps
    the change where a reader would look for it.
- **A duration in `LedgerBusy`'s message** (§5.3).
- **A `status` command** showing the mode (AI §2 expected one here). It is
  outside the agreed scope, and `list-config` already shows the mode.
- **A backend interface or `Protocol` in front of `kohle/db`.** The user
  decided against it. The module functions are the seam (§7, Extension
  points).

---

## 9. Issue mapping, per-slice files and tests

**Order: 059 → 060 → 061 → 062 → 063.** This is the issues' dependency order.
062 depends on nothing and could land first. Landing it fourth means it also
adds the busy branch to `snapshot_ledger`.

### 059: `snapshot <path>`

Production changes:

- `kohle/db/schema.py`: `_open_checked(path)`, `open_ledger` through it,
  `snapshot_ledger(path, dest)`, and the docstring (§4).
- `kohle/infrastructure/infra_errors.py`: `SnapshotExists`, `SnapshotFailed`.
- `kohle/app/cli/cli.py`: `snapshot_cmd` with `opens_ledger=False`, and the
  updated `_KohleCommand` docstring. `writes=` arrives in 061.

Tests, in `tests/test_snapshot.py` (new). The live ledger is built with
`write_init_rc` and `run_init` at `KOHLE_DB`, then given accounts, a unit and
a `record` through `CliRunner` with no `obj`.

- **A snapshot is written:** exit 0. The destination directory then holds
  only the snapshot: no `-journal`, `-wal`, `-shm` or `.tmp`.
- **It opens as an ordinary ledger:** with `KOHLE_DB` pointed at the
  snapshot, `balance Cash` and `list-accounts` print exactly what they print
  on the live ledger.
- **An existing path is refused,** each with exit 1, the `SnapshotExists`
  text, and the existing bytes unchanged:
  - a non-empty file;
  - an empty file (SQLite alone would accept it);
  - a directory;
  - a dangling symlink.
- **The live ledger is untouched:** its bytes and mtime are unchanged, and
  the `Operation` and `OperationGroup` counts read through a writer engine
  are unchanged.
- **A missing ledger:** exactly the existing `no ledger at …; run
  \`kohle-cli init\`` line, exit 1, and neither the ledger nor `dest`
  exists.
- **A ledger behind:** built with `_build(BEHIND)`. The `migrate` line
  appears and `dest` does not exist.
- **A missing parent directory:** exit 1, `SnapshotFailed`'s text, and nothing
  created.
- **A failure leaves nothing:** monkeypatch `os.fsync` in `kohle.db.schema` to
  raise `OSError`. Exit 1, no `dest`, and no `.tmp` in the directory.
- **Structural:** no `.py` file under `kohle/` outside `kohle/db/` contains
  `VACUUM`, `mode=ro` or `mode=rw`. This is 059's "SQLite-specific code sits
  with the connection code"; 060 keeps it true.
- **`tests/test_real_user_paths.py`:** add `snapshot <tmp>` to the recorded
  invocations.

README: the 059 row in §6.

### 060: `ledger.mode` and read-only open

Production changes:

- `kohle/infrastructure/device_config.py`: §3.1.
- `kohle/db/connection.py`: `ledger_mode`, `ledger_url(path, mode)`.
- `kohle/db/schema.py`: `mode` on `_open_checked`, `open_ledger` and
  `snapshot_ledger`; `"writer"` at the staged and migrate call sites.
- `kohle/infrastructure/infra_errors.py`: `NoLedger(path, mode)`.
- `kohle/use_cases/ledger.py`: `ledger_url(path, "writer")`.
- `kohle/app/cli/cli.py`: the hook passes `mode`; `snapshot_cmd` passes
  `ledger_mode(config)`.
- `kohle/app/tui/tui.py`, `table_editor.py`, `kohle/db/migrations/env.py`:
  §3.5.

Tests in `tests/test_reader.py` (new). A `reader` fixture:

1. builds the live ledger as in 059;
2. runs `snapshot` into `tmp_path / "copy" / "kohle.db"`;
3. points `KOHLE_DB` at the copy;
4. writes `ledger.mode = "reader"` with `write_config`.

This meets 060's "build the reader ledger from a snapshot". The autouse
fixture already keeps the real config out of reach.

- **The key:**
  - `list-config` shows `ledger.mode = writer  (default)` with no file, and
    `reader  (file)` with the fixture;
  - `get-config ledger.mode` prints `reader`;
  - `[ledger]` with `mode = "reader"` is equivalent to the dotted form.
- **An invalid value:** `ledger.mode = "Reader"` makes `list-accounts` exit 1
  with one line naming the file, `ledger.mode` and `writer, reader`.
  `--help` still exits 0.
- **Reads work:** `balance Cash`, `list-accounts`, `net-worth` and
  `list-settings` print what they print on the writer. The copy's bytes and
  mtime are unchanged afterwards.
- **The URL is read-only:**
  - `ledger_url(p, "reader")` ends in `?mode=ro&uri=true`;
  - `AddAccount(open_ledger(copy, "reader").unwrap()()).execute(...)` returns
    an `Err` whose text contains `readonly`, and no account exists.
- **A missing file on a reader:**
  - exit 1, the reader wording, and no `run \`kohle-cli init\``;
  - neither the file nor its parent directory exists;
  - with an injected-free `CliRunner`, `list-accounts` is the command.
- **Any file, not only snapshots:** the live ledger itself, opened with
  `ledger.mode = "reader"`, reads, and its bytes are unchanged.
- **Edits to existing tests, whose outputs change on purpose:**
  - `test_config_commands.py::test_list_config_shows_value_and_source` gains
    the `ledger.mode` line in all three expected outputs;
  - `test_device_config.py`'s unknown-key expectation lists
    `ledger.path, ledger.mode`.

README: the 060 row in §6.

### 061: a reader refuses write commands

Production changes:

- `kohle/domain/domain_errors.py`: `DeviceIsReader`.
- `kohle/app/cli/cli.py`:
  - `_KohleCommand.__init__` takes a required `writes`;
  - `invoke` refuses (§2.1);
  - all 35 decorators declare `writes` as in §2.2.

Tests, in `tests/test_reader.py`:

- **`_WRITE_ARGV`:** a valid argument list for each `writes=True` command.
  - `import-statement` uses `tests/fixtures/deutsche_bank_statement.csv`,
    because `click.Path(exists=True)` needs a real file.
  - Structural check: its keys equal
    `{n for n, c in cli.commands.items() if c.writes}`.
- **Each write command on the reader** (parametrised):
  - exit 1;
  - the output is exactly
    `` Error: this device is configured as a reader; `ledger.mode` is set in <config path>\n ``;
  - no `readonly` in the output;
  - the copy's bytes are unchanged.
  - Exact equality also proves the message names no transport.
- **Up front:**
  - `fetch-prices`, with `kohle.app.cli.cli.load_price_plugins` and
    `call_price_plugins` monkeypatched to raise, still exits 1 with the
    reader message;
  - the same holds for `import-statement` with `load_plugins` patched;
  - `init` with no `init.rc` and `KOHLE_DB` at a missing path gives the reader
    message and creates nothing.
- **An injected factory:** `add-account` with `obj=session_factory` and a
  reader config is refused, with zero `Account` and `OperationGroup` rows.
- **`_READ_ARGV`:** a valid argument list for each `writes=False` command,
  `snapshot` to a temp path included.
  - Structural check: its keys equal the `writes=False` commands.
  - Each runs exit 0 on the reader, and the copy's bytes are unchanged
    afterwards.
- **039:** `{"balance", "net-worth", "positions", "realised",
  "net-worth-history"}` are all `writes=False`.
- **Writer unchanged:** with `ledger.mode = "writer"` written explicitly,
  `add-account` succeeds. The rest of the suite covers the default.
- **The flag is required:** `_KohleCommand("x")` raises `TypeError`.

README: the 061 row in §6.

### 062: writers wait for a competing writer

Production changes:

- `kohle/db/connection.py`: `BUSY_TIMEOUT_SECONDS`, `make_engine`'s
  `connect_args`, `is_busy`.
- `kohle/infrastructure/infra_errors.py`: `LedgerBusy`.
- `kohle/infrastructure/transaction_context.py`, `kohle/infrastructure/uow.py`,
  and `check_schema` and `snapshot_ledger` in `kohle/db/schema.py`: the busy
  branches (§5.3).

Tests, in `tests/test_busy.py` (new). There is one real ledger, built by
`run_init`. The competing process is a raw `sqlite3` connection in a thread,
which signals an `Event` once it holds its lock; this is the pattern that was
checked in the scratchpad.

- **The setting:**
  - `PRAGMA busy_timeout` on a connection from `make_engine` reads `30000`;
  - the same holds on an engine from `open_ledger(path, "reader")`.
- **Waiting succeeds:**
  - the holder runs `BEGIN IMMEDIATE`, inserts, holds 0.5 s and commits;
  - meanwhile `add-account Cash` through `CliRunner` with no `obj` exits 0;
  - both rows exist.
- **Timing out, at a statement:**
  - monkeypatch `kohle.db.connection.BUSY_TIMEOUT_SECONDS` to `0.2`;
  - the holder holds 1.5 s;
  - `add-account` exits 1, the output is exactly
    `Error: the ledger stayed locked by another process; nothing was changed, try again\n`,
    with no `database is locked` and no `Traceback`;
  - after the holder commits, no `Cash` account exists.
- **Timing out at commit:**
  - with the timeout patched, the holder runs `BEGIN`, reads, and holds its
    read lock for 1.5 s;
  - `add-account` exits 1 with the same message.
  - This exercises `DbTransaction.execute`.
- **Timing out in the check:** the holder runs `BEGIN EXCLUSIVE`, and
  `list-accounts` exits 1 with the same message.
- **`is_busy`:** true for a captured busy `OperationalError`; false for a
  readonly one and for a plain `ValueError`.

README: the 062 row in §6.

### 063: documentation

Production changes: none. `README.md` as in §6, and the "Device config"
`ledger.mode` entry links to the new section.

Review checks, since there is no test:

- "Running" and "First run" do not mention the topic;
- Syncthing, `rsync`, the Pi and cron appear only as examples;
- every item in issue 063's acceptance list is present.

---

## 10. Gaps in the spec and issues, and points for the user

1. **The spec's freeze is uncommitted.** The working tree shows
   `dev/inbox/device-topology-and-sync.md` deleted and
   `dev/specs/device-topology-and-sync.md` untracked. Commit the move before
   implementation starts.
2. **The default `writer` and a lost `config.toml`.** A reader whose file goes
   missing opens its copy read-write. This is the device-config spec's
   handed-over warning, accepted by the user's choice of default (§3.1). The
   backstops are outside kohle, and the docs state them.
3. **On a reader, a copy that is behind points to `migrate`, which the reader
   refuses.**
   - The two messages together lead to the writer, but not directly.
   - The issues do not cover this, so it is not designed.
   - If wanted, the change is one line: `LedgerBehind` takes the mode as
     `NoLedger` does, and on a reader says "…; migrate it on the device that
     writes it".
4. **062's baseline is not "fail at once".** Python's `sqlite3` already
   waited 5 s. The design makes the wait explicit and sets it to 30 s. 30 s
   is a pick (§5.2).
5. **The busy timeout applies to reader engines too,** although the issue says
   "writer connections" (§5.2).
6. **`migrate`'s backup copy waits without limit** on a locked ledger, unlike
   the 30 s elsewhere. This is CPython's backup loop, and it is unchanged.
7. **`snapshot` picks the issues leave open:**
   - an existing path is refused at the start, and a file created at `dest`
     during the milliseconds of the copy would be replaced (§7);
   - parent directories are not created;
   - the file is 0600;
   - it is allowed on a reader;
   - it runs the schema check, so a ledger that is behind is refused;
   - a hard kill can leave a hidden `.tmp` beside `dest`.
8. **Usage errors come before the reader refusal.** `record` with missing
   arguments on a reader exits 2 with Click's usage message, as `--help`
   works on a reader.
9. **No up-front refusal outside the CLI.**
   - The TUI's write actions on a reader are stopped by `mode=ro` only, until
     `tui-wiring` adds a refusal.
   - `alembic upgrade` from the repo on a reader fails with SQLite's readonly
     error.
10. **A command wrongly declared `writes=False`** shows SQLite's raw readonly
    error on a reader. The reader test table catches that before release; it
    is not given a nicer message on purpose (§2.5).
11. **061 touches every command decorator** (35 lines). This is the price of
    the required declaration (§2.1).
12. **The messages are picks:**
    - `DeviceIsReader`;
    - the reader `NoLedger`;
    - `LedgerBusy`;
    - `SnapshotExists` and `SnapshotFailed`;
    - `snapshot`'s success line.
13. **"The docs" is a README section placed last** (§6), not a file under
    `docs/`, which holds design transcripts.
14. **The command name `snapshot`** follows the issue. `cli-command-naming` may
    rename it with the rest.
15. **The spec still lists open questions that this scope settles or
    defers.**
    - "How does a reader device know it is read-only" is answered by the
      config key.
    - The others (inbox, transport, backup, phone reader, ESP32) are
      deferred by the user's scope.
    - The spec is frozen, so it is not edited here.
16. **`AGENTS.md` should gain the §6 sentence** after landing. The user edits
    it.
