# Design: Device config

Spec: `dev/specs/device-config.md` (frozen)
Issues: `dev/issues/054`–`058`
Precedent: `dev/design/app-initialization.md`, cited as AI §n. It gave the
ledger `SETTINGS` registry (AI §7.2), `ledger_path()` (AI §4.1), the
init-file reader (AI §8.1) and the check hook in `invoke` (AI §6.1). This
design extends each of those and adds no parallel structure.

Layering stays as `AGENTS.md` describes it: `app -> use_cases -> services ->
infrastructure/domain`. Functions return `Result[T, E]`. Domain errors are
`Exception` subclasses used as values and are never raised. `kohle/db/`
counts as infrastructure.

The init file is called `init.toml` throughout. A separate `change` renames
`init.rc` to `init.toml` in the code (§13, ordering note).

The three choices the spec leaves to design are settled in §2 and §3. Where the
issues and the spec disagree, or where the design had to pick behaviour neither
pins down, the pick is listed in §14 for the user to confirm.

---

## 1. Summary of the shape

| File | Change | Issue |
|---|---|---|
| `kohle/infrastructure/device_config.py` | **new**. `config_dir`, `config_path`, `DeviceKey`, `DEVICE_KEYS`, `validate_device_config`, `DeviceConfig`, `load_device_config`, `Effective`, `effective` (§4). | 055, 056, 057 |
| `kohle/domain/domain_errors.py` | `DeviceConfigError` family (055, 056), `DeviceKeyNotASetting` (058) (§5). | 055, 056, 058 |
| `kohle/db/connection.py` | `ledger_path(config)`. The XDG default and the `KOHLE_DB` override move into the registry (§6). | 055 |
| `kohle/app/cli/cli.py` | 055: `_KohleCommand` replaces `_LedgerCommand`; `pass_device_config`; `init` and `migrate` take `opens_ledger=False` and the config; `_init_file_path` uses `config_dir()`. 057: `list-config`, `get-config`, `_with_source`. 058: the source on `list-settings`, and `set-setting` refusing device keys (§7, §9). | 055, 057, 058 |
| `kohle/app/tui/tui.py`, `kohle/app/tui/widgets/table_editor/table_editor.py` | Load the config, then `ledger_path(config)` (§8.1). | 055 |
| `kohle/db/migrations/env.py` | Load the config in the branches that resolve the ledger. Report a bad file as Alembic's `CommandError` (§8.2). | 055 |
| `tests/conftest.py` | The autouse fixture also redirects `HOME`. A `write_config` fixture is added (§15.1). | 054, 055 |
| `tests/test_real_user_paths.py` | **new**. Audit-hook proof that no real per-user kohle path is opened (§15.1). | 054 |
| `tests/test_device_config.py` | **new** (§15). | 055–058 |
| `tests/test_ledger_location.py`, `tests/test_cli.py` | `ledger_path` takes a config. The two `ledger_path` monkeypatches accept it (§7.4). | 055 |
| `README.md` | The device-config section, the precedence, the new commands and the split between the two scopes (§10). | 055–058 |

No dependency changes. `uv.lock` is untouched.

---

## 2. Decision 1: the registry lives in `kohle/infrastructure/device_config.py`

**Decision.** The device-key registry, its validators, the file reader and the
precedence rule all live in one new module,
`kohle/infrastructure/device_config.py`. Its errors go in
`kohle/domain/domain_errors.py`, beside `SettingError`.

These constraints decide the location:

- **`kohle/db/connection.py` must consume it.** The spec puts the file into
  `ledger_path()` as a middle source. `connection.py` is infrastructure, so the
  registry must sit at or below that layer. That rules out `kohle/use_cases/`,
  where the ledger `SETTINGS` registry lives.
- **`env.py` and the TUI must reach it without importing the app layer.**
  `env.py` already imports only `kohle.db.connection` and
  `kohle.domain.models`. One more infrastructure import keeps it that way.
- **Device keys are not all about the database.** The three keys
  `device-topology-and-sync` brings (role, lock wait, backup destination) all
  feed `kohle/db/`. The spec also names `configurable-net-worth-sampling` and
  `budgeting` as future owners of device keys, and those may have nothing to do
  with the database. So the registry does not go in `kohle/db/`.
- **It reads a file and the environment.** That is infrastructure work, not
  domain work, so it does not go in `kohle/domain/`.
- **A top-level `kohle/config.py` would sit outside the layer map** in
  `AGENTS.md`. Every existing module belongs to one of its layers.

**Why the errors are in `domain_errors.py` and not `infra_errors.py`.** The
spec calls them "domain error values". They also mirror `UnknownSetting` and
`InvalidSettingValue`, which live there. Infrastructure already imports from
`kohle.domain` (`crud.py`, `transaction_context.py`), so the direction is
allowed.

**What stays out of the module.** It knows TOML, XDG paths, `KOHLE_DB` and
the keys. It knows nothing about Click, SQLite or ledger settings.
`kohle/use_cases/settings.py` does not import it either. The two registries
meet only in the CLI, which is the one place where a user can confuse the two
scopes (§9.6).

---

## 3. Decision 2: command names and output layout

### 3.1 Names: `list-config` and `get-config`

The spec writes `config list` and `config get <key>`. Issue 057 adds "Flat
naming, as the existing commands". The two conflict: `config list` is a Click
subgroup, and there are no subgroups today.

**Decision: follow the issue.** The commands are `list-config` and
`get-config KEY`. That is the flat verb-object style the existing commands
use (`list-settings`, `set-setting`), as AI §10 recorded. The reasons:

- **Groups are the open question of `cli-command-naming`.** Its brief calls
  grouping "the main structural choice" and leaves it to a Q&A. The first
  subgroup would decide that question early.
- **They sit beside `list-settings` in `--help`**, which is where a user
  looking for "settings" will find them.

This is §14 item 1. If the user wants the spec's spelling, it is a
self-contained change in 057: a `@cli.group(name="config", cls=...)` whose
`command_class` is `_KohleCommand`, with `opens_ledger=False` on both
subcommands.

### 3.2 `list-config`

```
$ kohle-cli list-config
ledger.path = /home/hari/.local/share/kohle/kohle.db  (default)

file: /home/hari/.config/kohle/config.toml (not found)
```

```
$ KOHLE_DB=/tmp/scratch.db kohle-cli list-config
ledger.path = /tmp/scratch.db  (KOHLE_DB)

file: /home/hari/.config/kohle/config.toml
```

- **One line per key, in registry order:** `key = value  (source)`. The
  source is exactly one of the spec's tokens: `default`, `file`, `KOHLE_DB`.
- **`key = value` is the shape `list-settings` already uses** (`state = BW`).
  The two listings read alike, and the dotted key is the one to write in the
  file.
- **The value is the effective, canonical value.** A file entry of
  `~/books/kohle.db` prints as `/home/hari/books/kohle.db  (file)`. That shows
  the expansion the user actually gets, which is the point when debugging.
- **The footer names the file kohle reads, and says `(not found)` when it is
  missing.** The spec does not ask for this. The design adds it because the
  most likely reason a user's `ledger.path` "does nothing" is that their file
  is not where kohle looks (an `XDG_CONFIG_HOME` mismatch). The `file:` label
  ties it to the `file` source token. It sits below a blank line, as
  `list-settings` sets its `ledger:` and `revision:` lines apart (AI §2). This
  is §14 item 6.
- **A value shadowed by `KOHLE_DB` is not shown.** The source token already
  says the file was overridden, and git config behaves the same way.
- **Not a `tabulate` table.** With one key, and about four after
  `device-topology-and-sync`, a header row costs more than it helps. One
  rendering for "value with source" can also be shared with `list-settings`
  (§3.4).

### 3.3 `get-config KEY`

```
$ kohle-cli get-config ledger.path
/home/hari/.local/share/kohle/kohle.db
```

- **It prints the bare effective value and nothing else**, so
  `sqlite3 "$(kohle-cli get-config ledger.path)"` works. The source is in
  `list-config`.
- **An unknown key exits 1** with
  `unknown device key 'x'; known device keys: ledger.path`.
- **`KEY` is a plain argument, not a `click.Choice`.** The reason is the same
  as for `set-setting KEY` (AI §10): a `Choice` would give a Click usage error
  (exit 2) in Click's own wording, not the registry's.

### 3.4 `list-settings`: the source on the path line

```
state = BW

ledger:   /home/hari/.local/share/kohle/kohle.db  (default)
revision: e5a1c3b7d902
```

- **The same `  (source)` suffix as `list-config`**, through one helper
  `_with_source(value, source)` in `cli.py`. The two commands cannot render
  the source differently.
- **The path still comes from `PRAGMA database_list`** (AI §2), so the line
  never names a file other than the one read. The source comes from
  `effective(config, "ledger.path").source`: it says how the path was chosen.
  The path is symlink-resolved and the chosen value is not, so the two can
  differ in spelling. They never differ in which file they mean.
- **With an injected in-memory factory, the line stays `ledger:   (in memory)`
  with no source.** No path was resolved, so a source would be false.
- **No config-file line is added.** The spec says `list-settings` "still shows
  only ledger settings, the ledger path and the revision".

---

## 4. The module (`kohle/infrastructure/device_config.py`)

The module docstring should state the rule this feature exists for: device
settings never travel with a copy of the ledger, and kohle never writes this
file.

### 4.1 Where the file is

```python
def config_dir() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    return (Path(config_home) if config_home else Path.home() / ".config") / "kohle"

def config_path() -> Path:
    return config_dir() / "config.toml"
```

- **`config_dir()` is shared with `init.toml`.** `cli.py`'s `_init_file_path()`
  becomes `config_dir() / "init.toml"`. The XDG rule then exists once. Only
  `cli.py` knows the init file's name, so AI §8.1's "no module below the app
  layer knows the init file exists" still holds.
- **An empty `XDG_CONFIG_HOME` counts as unset**, the same as `KOHLE_DB` and
  `XDG_DATA_HOME` (AI §4.1).
- **No `KOHLE_CONFIG` override.** This is a spec non-goal.

### 4.2 The registry

```python
@dataclass(frozen=True, slots=True)
class DeviceKey:
    validate: Callable[[object], Result[object, InvalidDeviceValue]]
    default: Callable[[], object]


def _ledger_path_value(value: object) -> Result[object, InvalidDeviceValue]:
    # os.path.expanduser, not Path.expanduser: an unexpandable ~user is left
    # as is (and then rejected as relative) instead of raising RuntimeError.
    if isinstance(value, str):
        path = Path(os.path.expanduser(value))
        if path.is_absolute():
            return Result.ok(path)
    return Result.err(InvalidDeviceValue("ledger.path", value, "an absolute path, or one starting with ~"))


def _default_ledger_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    data_dir = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return data_dir / "kohle" / "kohle.db"


# Device keys, in listing order. A later feature adds its key here, and the
# file, list-config and get-config follow. Ledger settings are SETTINGS in
# kohle/use_cases/settings.py, a separate registry.
DEVICE_KEYS: dict[str, DeviceKey] = {
    "ledger.path": DeviceKey(_ledger_path_value, _default_ledger_path),
}
```

- **The spec says it mirrors `SETTINGS`, and it does in the parts that
  matter.** It is a module-level dict from key to validator. Each validator
  takes `object`, because TOML can give any type, and returns `Result`.
- **It differs in two ways, each forced:**
  - It has a `default`, because a missing file or key means "take the
    default" (spec) and `list-config` prints it. The default is a callable
    because `ledger.path`'s default reads `XDG_DATA_HOME` and `HOME` when the
    command runs, not at import (AI §4.1).
  - Validated values are typed per key (`Path` here), not canonical strings.
    `SETTINGS` stringifies because it stores to a `String` column. Device
    values never leave the process.
- **The `ledger.path` validator checks form only,** as the spec says:
  - it must be a TOML string;
  - a leading `~` (or `~user`) is expanded;
  - the result must be absolute.

  `"kohle.db"`, `""`, `1` and `{}` are rejected. Whether a ledger exists
  there is the existing `NoLedger` check's job. The path is not resolved, and
  `..` is not normalised.
- **`_default_ledger_path` moves here from `ledger_path()`, unchanged.**
  `connection.py` cannot hold it, because the registry needs it and
  `connection.py` imports this module (§6).

### 4.3 Reading the file

```python
def validate_device_config(raw: Mapping[str, object]) -> Result[dict[str, object], UnknownDeviceKey | InvalidDeviceValue]
def load_device_config() -> Result[DeviceConfig, BadConfigFile]


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    path: Path                  # the file read, or looked for
    found: bool                 # 057: list-config's footer
    values: dict[str, object]   # validated values set in the file; absent keys take their default
```

**`validate_device_config(raw)`** mirrors `validate_settings`:

- It flattens `raw` to dotted keys (below).
- It goes through them in file order, which `tomllib` keeps.
- The first unregistered key gives `UnknownDeviceKey(key, list(DEVICE_KEYS))`.
- The first invalid value gives the validator's `Err`.
- Only one error is reported, which gives the spec's one line.
- It is pure. A later `config set` (a spec non-goal) would reuse it unchanged.

**Flattening.** `tomllib` returns `[ledger]` / `path = "…"` and
`ledger.path = "…"` as the same `{"ledger": {"path": "…"}}`. Checked against
Python 3.12's `tomllib`. So the equivalence the spec asks for comes from the
parser, and flattening only has to join the segments:

```python
def _flatten(table: Mapping[str, object], prefix: str = "") -> Iterator[tuple[str, object]]:
    for name, value in table.items():
        # A quoted key with a dot in it ("ledger.path" = ...) is a different
        # TOML key from the dotted one, so it is shown quoted and never
        # matches a registered key.
        key = prefix + (f'"{name}"' if "." in name else name)
        # A registered key's value is taken whole, so `ledger.path = {}`
        # reaches the validator instead of vanishing as an empty table.
        if isinstance(value, dict) and key not in DEVICE_KEYS:
            yield from _flatten(value, f"{key}.")
        else:
            yield key, value
```

- **`ledgr.path = "/x"` flattens to `ledgr.path`.** The error names the key
  the user wrote, as the spec asks.
- **Quoted dotted keys stay distinct.** Checked: `tomllib` gives
  `{"ledger.path": "/a", "ledger": {"path": "/b"}}` when both spellings are
  present. Rendering the quoted one as `"ledger.path"` keeps flattening
  one-to-one, so no duplicate-key rule is needed. The quoted form is reported
  as unknown, which matches TOML: it is a different key.
- **An empty table (`[ledger]` with nothing under it, or a typo'd `[foo]`)
  yields no keys and is accepted.** It configures nothing. §14 item 8.
- **An array of tables (`[[ledger]]`)** is a list at `ledger`, so it is an
  unknown key `ledger`.

**`load_device_config()`:**

```python
path = config_path()
try:
    with path.open("rb") as f:
        raw = tomllib.load(f)
except FileNotFoundError:
    return Result.ok(DeviceConfig(path, found=False, values={}))
except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
    return Result.err(BadConfigFile(path, str(e)))
except OSError as e:
    return Result.err(BadConfigFile(path, e.strerror or str(e)))
return validate_device_config(raw).map(...).map_err(lambda err: BadConfigFile(path, err))
```

- **A missing file is `Ok`** with every key at its default (spec). A missing
  `kohle/` directory is also `FileNotFoundError`.
- **`UnicodeDecodeError` is caught next to `TOMLDecodeError`.** Checked:
  `tomllib.load` decodes the bytes itself, and non-UTF-8 content raises
  `UnicodeDecodeError`, which is not a `TOMLDecodeError`. Without this clause,
  a file saved in Latin-1 would give a traceback on every command.
- **Other `OSError`s are caught** (permission denied, a directory at the path,
  a file where `kohle/` should be). This file is read on every command, unlike
  the init file. An unreadable file must give the spec's one line, not a
  traceback per command. `strerror` is used because `str(OSError)` repeats the
  path the message already names.
- **These are explicit types**, as the global rule requires. No new broad
  `except`.
- **It is read once and never written.** Nothing in kohle opens this path for
  writing.

### 4.4 Precedence: `effective(config, key)`

```python
Source = Literal["default", "file", "KOHLE_DB"]

@dataclass(frozen=True, slots=True)
class Effective:
    value: object
    source: Source

def effective(config: DeviceConfig, key: str) -> Effective:
    """`key` must be in DEVICE_KEYS."""
    # KOHLE_DB predates config.toml. It is the only environment variable that
    # overrides a device key, and the spec adds no others. It is taken as
    # given, unvalidated, as it was before this file existed.
    if key == "ledger.path" and (db := os.environ.get("KOHLE_DB")):
        return Effective(Path(db), "KOHLE_DB")
    if key in config.values:
        return Effective(config.values[key], "file")
    return Effective(DEVICE_KEYS[key].default(), "default")
```

- **The spec's precedence lives in this one function:** built-in default <
  file < existing environment variable. `ledger_path`, `list-config`,
  `get-config` and `list-settings` all read through it, so the source a
  listing shows is by construction the one that chose the path.
- **`KOHLE_DB` is a named special case, not a registry field.** The forcing
  facts:
  - the spec forbids new variables, so there will only ever be this one;
  - its value is used as given, while file values go through the validator.

  An `env` field would describe a variation that cannot occur, and it would
  need its own converter (§12).
- **An empty `KOHLE_DB` still counts as unset**, as today.
- **An unregistered key is a programming error** (`KeyError`). `get-config`
  checks membership first and builds the `UnknownDeviceKey` value itself
  (§9.4). No caller handles an impossible `Err`.

---

## 5. Errors (`kohle/domain/domain_errors.py`)

These follow the file's convention: `__str__` is the one-line user message,
and frontends print `str(err)`.

| Class | Fields | Message | Issue |
|---|---|---|---|
| `DeviceConfigError(Exception)` | | base | 055 |
| `InvalidDeviceValue` | `key, value, expected` | `invalid {key} {value!r}; expected {expected}` | 055 |
| `BadConfigFile` | `path, reason: str \| UnknownDeviceKey \| InvalidDeviceValue` | `{path}: {reason}` | 055 |
| `UnknownDeviceKey` | `key, known` | `unknown device key {key!r}; known device keys: {", ".join(known)}` | 056 |
| `DeviceKeyNotASetting(SettingError)` | `key, config_path` | `` `{key}` is a device key; edit {config_path} `` | 058 |

What a user sees (`Error: ` is Click's prefix):

```
Error: /home/hari/.config/kohle/config.toml: unknown device key 'ledgr.path'; known device keys: ledger.path
Error: /home/hari/.config/kohle/config.toml: invalid ledger.path 'kohle.db'; expected an absolute path, or one starting with ~
Error: /home/hari/.config/kohle/config.toml: Expected '=' after a key in a key/value pair (at line 1, column 7)
Error: /home/hari/.config/kohle/config.toml: Permission denied
Error: `ledger.path` is a device key; edit /home/hari/.config/kohle/config.toml
```

- **`BadConfigFile` is the only error that names the file.** Validators and
  `UnknownDeviceKey` stay path-agnostic, as `_bundesland` is. That lets
  `get-config`, where no file is involved, reuse `UnknownDeviceKey` bare. The
  loader adds the path in exactly one place. CLI, TUI and `env.py` all print
  the same line because the path is in the value, not added by each frontend.
  This differs from `init`, where the CLI prefixes the path (AI §8.3): that
  file has only one reader.
- **The wording says "device key"** where the settings errors say "setting".
  Someone who mixes up the two scopes is told which one they hit.
- **`DeviceKeyNotASetting` is a `SettingError`.** It answers a `set-setting`
  call. The backticks are literal: the spec's text puts them there, and
  existing messages already use literal backticks around code
  (``run `kohle-cli init` ``). §14 item 7.

---

## 6. Path resolution (`kohle/db/connection.py`)

```python
def ledger_path(config: DeviceConfig) -> Path:
    # The registry's validator, default and KOHLE_DB all give a Path.
    return cast(Path, effective(config, "ledger.path").value)
```

- **The spec's "`ledger_path()` gains the file as a middle source" holds**:
  `KOHLE_DB`, then `ledger.path`, then the XDG default. The name and module
  stay, so every caller keeps its import and the CLI test seam
  (`kohle.app.cli.cli.ledger_path`) does not move.
- **It takes the loaded config instead of reading the file itself.** That is
  how "read once per command, before any engine is created" holds: the caller
  loads once and passes the result. It also keeps `ledger_path` a total
  function. It does not return a `Result`, because every error was handled
  when the file was loaded.
- **A caller cannot forget the file.** It must have a `DeviceConfig` to call
  `ledger_path` at all, and the only way to get one is through the validating
  loader. That is the guarantee that CLI, TUI and Alembic resolve alike
  (§8), without a shared "resolve" helper.
- **`connection.py` imports `device_config`, never the other way round**, so
  there is no cycle.

---

## 7. The CLI hook (`kohle/app/cli/cli.py`)

### 7.1 One command class with an `opens_ledger` flag

```python
_DEVICE_CONFIG = "kohle.device_config"
pass_device_config = click.decorators.pass_meta_key(
    _DEVICE_CONFIG, doc_description="the device config read for this command"
)


class _KohleCommand(click.Command):
    """Reads config.toml, then opens and checks the ledger, before the body
    runs. Both happen in invoke because Click runs the group callback before
    parsing the subcommand's arguments, and `<command> --help` must work with
    a bad config file or no ledger. opens_ledger=False skips only the ledger.
    A factory injected through obj (tests) is the caller's schema, unchecked;
    the config file is read regardless."""

    def __init__(self, *args, opens_ledger: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.opens_ledger = opens_ledger

    def invoke(self, ctx: click.Context) -> object:
        loaded = load_device_config()
        if loaded.is_err:
            raise click.ClickException(str(loaded.unwrap_err()))
        config = loaded.unwrap()
        ctx.meta[_DEVICE_CONFIG] = config
        if self.opens_ledger and ctx.obj is None:
            opened = open_ledger(ledger_path(config))
            if opened.is_err:
                raise click.ClickException(str(opened.unwrap_err()))
            ctx.obj = opened.unwrap()
        return super().invoke(ctx)


class _KohleGroup(click.Group):
    # Every command declared on `cli` reads the config and, unless it passes
    # opens_ledger=False, opens the ledger. Nothing passes cls=.
    command_class = _KohleCommand
```

Checked against Click 8.3.1 in the scratchpad:

- **`@cli.command(opens_ledger=False)` reaches the constructor.**
  `Group.command` passes extra keyword arguments to `command_class`.
- **`kohle-cli list-config --help` runs the group callback but not
  `Command.invoke`.**
- **`kohle-cli --help` runs neither.**
- **`ctx.meta` set in `invoke` is what `pass_meta_key` reads in the
  callback.**

How it behaves:

- **Every command reads the config first**, including `init`, `migrate`,
  `list-importer-plugins` and the two config commands. A bad file stops each of
  them before its body runs, so before any engine, file or init-file read
  (spec, 056).
- **`--help` in both forms is exempt, and so are usage errors.** Click exits
  in `make_context`, before `invoke`. A bad file never blocks help (§14
  item 2).
- **Opting out of the ledger cannot opt out of the config.** AI §6.1 opted out
  with `cls=click.Command`. Kept here, that spelling would now skip the
  config check too, silently. The flag removes any reason to pass `cls=`, and
  a structural test asserts that every command in `cli.commands` is a
  `_KohleCommand` (§15.3).
- **An injected factory still gets the config check.** Tests inject factories
  with an empty temp `XDG_CONFIG_HOME` (§15.1), so this costs nothing, and the
  056 tests can run through `CliRunner` either way.
- **The config is passed to bodies through `ctx.meta`, not `ctx.obj`.** `obj`
  is the session factory, which tests inject. `meta` is Click's documented
  dict shared down the context chain. `pass_meta_key` is Click's own decorator
  for it, so no helper is written.
- **Ordering inside `invoke`**: load the config, then resolve the path, then
  open the ledger. `ledger_path` needs the config, so it cannot come first.

### 7.2 Decorator order for commands that need both

```python
@cli.command()
@pass_device_config
@click.pass_obj
def list_settings_cmd(make_session, config: DeviceConfig): ...
```

The innermost decorator's argument comes first.

### 7.3 The slice before 056

In 055 the loader handles a missing file and invalid values. A TOML syntax
error, a decode error or an `OSError` still raises from `tomllib` or `open`,
with a traceback, until 056 adds the three `except` clauses. Unknown keys are
skipped until 056 adds `UnknownDeviceKey`. AI §6.2 accepted the same kind of
scaffolding.

### 7.4 Test seams

- `test_injected_factory_is_used_and_real_db_is_untouched`:
  `forbidden_ledger_path` takes `*_`. It must still never be called with an
  injected factory, and it is not.
- `test_default_obj_opens_the_ledger_at_the_resolved_path`: the `Mock`'s
  `side_effect` takes the config argument.

---

## 8. The TUI and the Alembic environment

### 8.1 `kohle-tui`

```python
def main():
    loaded = load_device_config()
    if loaded.is_err:
        sys.exit(str(loaded.unwrap_err()))
    opened = open_ledger(ledger_path(loaded.unwrap()))
    ...
```

- **It imports `kohle.infrastructure.device_config` and `kohle.db`, never
  `kohle.app.cli`.**
- **The config is read once, at start-up.** A running TUI does not see edits
  (the spec rules out live reload); restart it.
- **The demo app in `table_editor.py`** calls
  `open_ledger(ledger_path(load_device_config().unwrap())).unwrap()`, keeping
  that demo's existing unwrap style.
- **`kohle-tui` still cannot start** (missing imports, AI §12), so review
  verifies this, not a test.

### 8.2 `env.py`

```python
from alembic.util import CommandError
from kohle.infrastructure.device_config import load_device_config


def _ledger() -> Path:
    # Alembic's own clean failure: its command line prints "FAILED: <line>"
    # and exits 1, instead of a traceback.
    loaded = load_device_config()
    if loaded.is_err:
        raise CommandError(str(loaded.unwrap_err()))
    return ledger_path(loaded.unwrap())
```

- **Only the two branches that resolve the ledger call it:** offline mode, and
  online mode with no connection in `config.attributes`. The repo's `alembic`
  command and tests calling `command.upgrade(alembic_config(), ...)` go
  through these.
- **`init` and `migrate` never reach it.** They pass the staged file's
  connection (AI §3.4), so the config is not read a second time inside one
  `kohle-cli` command.
- **Why raise here, when the rest of the code returns values.** `env.py` is a
  script Alembic runs, and Alembic's contract with it is exceptions.
  `CommandError` is the type Alembic's command line turns into one clean line
  (checked: `CommandLine.run_cmd` catches it and calls `util.err`). This is
  the seam where the `Result` becomes the host framework's error, the same
  move the CLI makes with `ClickException`.

---

## 9. Commands

### 9.1 `init`

```python
@cli.command(name="init", opens_ledger=False)
@pass_device_config
def init_cmd(config: DeviceConfig) -> None:
    rc = _init_file_path()             # config_dir() / "init.toml"
    ...                                # read and validate, unchanged
    res = init_ledger(ledger_path(config), validated.unwrap())
```

- **A ledger is created at `ledger.path` when the file names one.** This is
  how a user puts a new ledger somewhere other than the XDG default without an
  environment variable.
- **The order now has three steps:** `config.toml` (in `invoke`), then
  `init.toml`, then the ledger. A bad `config.toml` stops `init` before it
  reads `init.toml`. A bad `init.toml` stops it before anything is created,
  as before.
- **`init.toml` is not merged into `config.toml`**, and the reverse does not
  happen either. Device keys are rejected there, as unknown settings (§9.6).

### 9.2 `migrate`

It takes `opens_ledger=False` and `@pass_device_config`, and calls
`migrate_ledger(ledger_path(config))`. Nothing else changes.

### 9.3 `list-config` (057)

```python
@cli.command(opens_ledger=False)
@pass_device_config
def list_config_cmd(config: DeviceConfig) -> None:
    for key in DEVICE_KEYS:
        e = effective(config, key)
        click.echo(f"{key} = {_with_source(e.value, e.source)}")
    click.echo()
    click.echo(f"file: {config.path}{'' if config.found else ' (not found)'}")
```

- **It never opens the ledger, never runs the schema check, and never builds
  an engine.** It needs neither `make_session` nor `ledger_path`. It works with
  the ledger missing, behind or ahead (spec).
- **On a bad file it fails like every other command** (spec: "every command
  except `--help`"). The error line names the file and the key, which is the
  same debugging information (§14 item 2).

### 9.4 `get-config KEY` (057)

```python
@cli.command(opens_ledger=False)
@click.argument("key")
@pass_device_config
def get_config_cmd(config: DeviceConfig, key: str) -> None:
    if key not in DEVICE_KEYS:
        raise click.ClickException(str(UnknownDeviceKey(key, list(DEVICE_KEYS))))
    click.echo(str(effective(config, key).value))
```

The CLI builds the domain error itself, as `list-accounts` already does with
`AccountNotFoundError` (`cli.py`).

### 9.5 `list-settings` (058)

It gains `@pass_device_config`. The path line becomes:

```python
ledger = report.ledger and _with_source(report.ledger, effective(config, "ledger.path").source)
click.echo(f"ledger:   {ledger or '(in memory)'}")
```

`SettingsReport` is unchanged. The source is a device fact, so the use case
does not carry it.

### 9.6 `set-setting` (058)

```python
@cli.command()
@click.argument("key")
@click.argument("value")
@pass_device_config
@click.pass_obj
def set_setting_cmd(make_session, config: DeviceConfig, key: str, value: str):
    if key in DEVICE_KEYS:
        raise click.ClickException(str(DeviceKeyNotASetting(key, config.path)))
    ...  # unchanged
```

- **The refusal comes before `SetSettings`**, so nothing is written and no
  `Operation` or `OperationGroup` is created (058).
- **The check is in the CLI, not in `validate_settings`.** These reasons
  decide it:
  - The message must name the config path. The CLI already holds the loaded
    config. `validate_settings` would have to read `XDG_CONFIG_HOME` inside a
    use case to rebuild it.
  - `kohle/use_cases/settings.py` stays free of any device-config import. The
    spec says the two are separate registries.
  - The CLI is the only frontend where a free-text key can name a device key.
    A TUI settings screen would offer `SETTINGS` keys only.
- **Unknown ledger keys behave as before** (`UnknownSetting`, listing
  `state`).
- **`set-setting` still opens the ledger before its body runs.** On a missing
  or outdated ledger, `set-setting ledger.path /x` therefore reports the
  ledger problem, not the device-key refusal (§14 item 5).

---

## 10. README and AGENTS.md

| Slice | Section |
|---|---|
| 055 | **New "Device config" section**, placed after "Where the ledger lives". It covers: `$XDG_CONFIG_HOME/kohle/config.toml` or `~/.config/kohle/config.toml`; TOML, with `[ledger]` / `path = …` equal to `ledger.path = …`; kohle never writes the file; it is read once per command; a missing file means defaults; the key list (`ledger.path`: absolute, or starting with `~`); precedence default < file < `KOHLE_DB`. **Two scopes:** ledger settings live in the `settings` table and travel with the ledger (`list-settings`, `set-setting`, `init.toml` once); device settings live in the file and stay on the machine. No secrets in the file; plugin variables stay environment variables. **"Where the ledger lives"** becomes the three-step order: `KOHLE_DB`, then `ledger.path`, then the XDG default. |
| 056 | One paragraph: an unknown key, an invalid value, a TOML syntax error or an unreadable file stops every command except `--help`, `init` and `migrate` included, with one line naming the file. |
| 057 | `list-config` and `get-config`, with the §3.2 example. Neither opens the ledger, so they are the way to debug a wrong `ledger.path`. |
| 058 | `list-settings`: the path line shows its source. `set-setting` refuses device keys and points to the file. |

`AGENTS.md`'s Context should gain this after landing. This design does not edit
it; the user does. Suggested replacement for the ledger-location sentence: "The
ledger lives at `KOHLE_DB`, else `ledger.path` in `config.toml`, else
`$XDG_DATA_HOME/kohle/kohle.db`; … Ledger-wide settings live in the `settings`
table, keyed by the registry in `kohle/use_cases/settings.py`. Device settings
live in `$XDG_CONFIG_HOME/kohle/config.toml`, keyed by the separate registry in
`kohle/infrastructure/device_config.py`; kohle never writes that file."

---

## 11. The decision categories

### State and data lifecycle

- **The config load is all-or-nothing.** Either every key in the file
  validates and the command runs with the whole config, or the command stops
  before doing anything. There is no partial config, such as applying the
  valid keys and warning about the rest. A typo that silently changes
  behaviour is exactly what 056 exists to prevent.
- **Nothing is persisted, so there is nothing to commit or roll back.** kohle
  only reads the file. The ledger lifecycle (staging, `UnitOfWork`, audit) is
  untouched.
- **"Before doing anything" is structural.** The load is the first statement
  of `_KohleCommand.invoke`. Nothing can be written before it: no engine, no
  `init.toml` read, no staged file, no plugin run.
- **Device settings are not audited, reversible or replayable through kohle.**
  This is deliberate. They are facts about one machine, kept in a file the
  user owns. Version control or backups of `~/.config` cover history. Ledger
  settings keep their `Operation` audit (AI §7.5).
- **Snapshot of the environment.** `effective()` reads `KOHLE_DB`,
  `XDG_DATA_HOME` and `HOME` when called. Within one command they do not
  change, so every caller in that command sees one consistent answer.
- **No module-level mutable state.** `DEVICE_KEYS` is a constant, like
  `SETTINGS`. Nothing is cached across commands or at import.

### Error propagation

| From | Caught where, as what | Becomes |
|---|---|---|
| `open` / `tomllib` | `load_device_config`: `FileNotFoundError` gives `Ok` with defaults; `TOMLDecodeError`, `UnicodeDecodeError` and `OSError` are explicit `except`s | `BadConfigFile(path, reason)` value |
| Unknown key, invalid value | `validate_device_config`, as values | `UnknownDeviceKey` / `InvalidDeviceValue`, wrapped in `BadConfigFile` by the loader |
| `BadConfigFile` reaching the CLI | `_KohleCommand.invoke` | `ClickException`: `Error: <line>`, exit 1 |
| `BadConfigFile` reaching the TUI | `main()` | `sys.exit(str(err))`: the line on stderr, exit 1 |
| `BadConfigFile` reaching `env.py` | `_ledger()` | `CommandError`: `FAILED: <line>`, exit 1 |
| `get-config` unknown key, `set-setting` device key | CLI builds the domain error | `ClickException(str(err))`, exit 1 |

What each layer knows about the one below:

- **`device_config.py`** knows TOML, XDG, `KOHLE_DB` and the registry. It knows
  nothing about Click, SQLite or ledger settings.
- **`connection.py`** knows `DeviceConfig` and `effective`. It knows nothing
  about TOML or the file's location.
- **The frontends (CLI, TUI, `env.py`)** know only that loading can fail with
  a printable error. Each turns it into its host's exit convention.
- **No new broad `except Exception`.** The `AGENTS.md` override stays limited
  to the two transaction seams.

### Concurrency and ownership

- **Single-threaded, no shared mutable state.** Each CLI process loads the
  config once. The loaded `DeviceConfig` is owned by the Click context
  (`ctx.meta`) for that one invocation. It is a frozen dataclass and never
  mutated.
- **Across processes there is nothing to protect.** kohle never writes the
  file, so two commands only ever read it. If a user saves the file while a
  command reads it, the command sees either the old or the new content, or a
  half-written file that fails as a syntax error with one line. A rerun fixes
  it. Most editors save atomically anyway.
- **A long-running TUI keeps the config it started with.** The spec rules out
  live reload.
- **If this module is reused elsewhere:** `load_device_config` and `effective`
  are pure apart from reading the environment and one file, so they are safe
  to call from any thread. Nothing here assumes the main thread.

### Reuse

What this uses instead of rebuilding:

- The `SETTINGS` pattern: a dict registry, validators from `object` to
  `Result`, and first-error-wins validation (AI §7.2).
- `tomllib`, which `cli.py` already imports for the init file.
- The existing `NoLedger`, `LedgerBehind` and `LedgerAhead` checks. A
  `ledger.path` with no ledger behind it is reported by `open_ledger`
  unchanged.
- AI §6.1's `invoke`-time hook and `Group.command_class`, extended with one
  constructor flag.
- Click's own `pass_meta_key` and `Context.meta`.
- Alembic's `CommandError` for `env.py`'s failure.
- The `click.ClickException(str(domain_error))` rendering, and building a
  domain error in the CLI as `list-accounts` does.

What is factored so the next feature reuses it:

- **`DEVICE_KEYS`.** `device-topology-and-sync` adds role, lock wait and backup
  destination. The spec names `configurable-net-worth-sampling` and
  `budgeting` as further owners. None of them may add a second mechanism
  (spec).
- **`config_dir()`.** One XDG rule for `config.toml` and `init.toml`.
- **`validate_device_config`**, so a later `config set` validates exactly as
  the loader does.
- **`_with_source`**, so any later listing of an effective value renders the
  source the same way.
- **The `ledger.path` validator is not generalised yet.** The backup
  destination in `device-topology-and-sync` will want the same check (absolute,
  `~` expanded). That feature should turn it into a validator that takes the
  key name, for example with `functools.partial`. Doing it now would be an
  abstraction with one user.

### Extension points

1. **`DEVICE_KEYS`.** The contract for a key a later feature adds:
   - The key is a dotted path of bare TOML segments. Registering `a.b` means
     the value at `a.b` is taken whole, even if it is a table, and handed to
     the validator.
   - The validator takes the raw TOML value (any type) and returns the
     canonical value, or `InvalidDeviceValue` with a human `expected`. It
     checks form only and does no I/O, so the per-command check stays cheap
     and real-world failures stay with the code that acts on the value.
   - The default is a zero-argument callable, evaluated when it is needed.
   - The value's type is whatever the validator returns. The default must
     return the same type, and the consumer narrows to it. Readers go through
     `effective(config, key)`.
   - `list-config` and `get-config` render values with `str()`. A key whose
     `str()` is not what a user would write (a `bool` prints `True`, TOML
     writes `true`) needs a rendering decision in that feature.
   - **No environment-variable override for new keys.** This is a spec
     non-goal. `KOHLE_DB` stays the only one.
   - The spec's note for `device-topology-and-sync` applies: a missing file
     means every key takes its default, so the default device role decides
     what a reader becomes when its file disappears.
2. **`_KohleCommand`'s `opens_ledger` flag.** New commands get the config read
   and the ledger check by default. `opens_ledger=False` is for commands that
   must run without a usable ledger: today `init`, `migrate`, `list-config` and
   `get-config`. There is no way to skip the config read, and the structural
   test enforces that.
3. **Getting the config:** in a CLI body, `@pass_device_config`; anywhere
   else, `load_device_config()` once at entry, then pass the `DeviceConfig`
   down.
4. **A `config set` / `config unset`** (spec non-goal) could be added later
   without changing anything here except adding `tomlkit`.
5. **No plugin-facing extension point.** Plugins cannot register device keys
   (spec non-goal). `KOHLE_PRICE_FILE` and `KOHLE_ALPHAVANTAGE_KEY` stay
   environment variables.

### Build vs. buy

| Component | Decision | Evaluated, and why not |
|---|---|---|
| TOML parsing | **Buy**: `tomllib` | Fixed by the spec. No dependency added. |
| Layered config (file + env + defaults + validation) | **Build**: one registry dict and one 10-line `effective()` | `pydantic-settings` has a TOML source, env layering and `extra="forbid"`, but it is a new dependency (the spec forbids that) and maps keys to generated env vars (`KOHLE_LEDGER__PATH`), which the spec forbids. `dynaconf` and `confuse` exist to merge several files and environments, which the spec rules out (one file, no merging), and both are new dependencies. |
| Config-to-command wiring | **Build** on Click's `Group.command_class` and `pass_meta_key` | Click's `default_map` / `auto_envvar_prefix` feed command options, but no key is an option (the spec allows no flags), and they would not cover the TUI or `env.py`. |
| XDG config directory | **Build** (3 lines, shared by both files) | `platformdirs.user_config_dir`, already a dependency, matches on Linux but returns `~/Library/Application Support` on macOS. The spec fixes XDG semantics, the same reasoning as AI §14. |
| `~` expansion | **Buy**: `os.path.expanduser` | `Path.expanduser` raises `RuntimeError` for an unknown `~user` (checked). `os.path.expanduser` leaves it unexpanded, so the absolute-path check rejects it as an ordinary invalid value. |
| Value validation | **Build**: per-key `Result` validators | `attrs` / `pydantic` validators raise. The codebase's error contract is values. |
| Test isolation proof | **Buy**: `sys.addaudithook` (stdlib) | Monkeypatching `open` or `tomllib.load` only sees the calls it patches. The `open` and `sqlite3.connect` audit events see every file and database open in the process (checked). |

### Abstractions introduced

| Abstraction | Forcing problem |
|---|---|
| `DEVICE_KEYS` / `DeviceKey(validate, default)` | The spec requires a fixed key list with one validator per key. `list-config` and a missing file both need each key's default. Two fields per key make a dataclass, not a tuple, for readable call sites. |
| `validate_device_config(raw)` | Mirrors `validate_settings`. It is the pure step a later `config set` reuses, and it keeps the loader's file handling apart from key rules. |
| `_flatten` | `tomllib` returns nested tables, and the registry is keyed by dotted path. It also covers the two traps in §4.3: a registered key whose value is a table, and a quoted dotted key. |
| `load_device_config()` / `DeviceConfig` | The file is read once per command, and the result must reach `ledger_path`, the config commands and `list-settings`. `found` exists for `list-config`'s footer. |
| `effective()` / `Effective` / `Source` | One precedence rule with four readers. Three of them need the source as well as the value. |
| `ledger_path(config)` (signature change) | The resolved path must include the file without reading it again (read once per command). |
| `config_dir()` | `config.toml` and `init.toml` share one XDG rule. |
| `_KohleCommand(opens_ledger=...)` | The config check must run on every command after `--help` parsing (AI §6.1 reasoning). A ledger opt-out must not be able to skip it. |
| `pass_device_config` | One line binding Click's `pass_meta_key` to the meta key, used by six commands. |
| `_with_source` | `list-config` and `list-settings` must render the source identically. |
| `BadConfigFile` wrapping a reason | Every file error must name the file, while validators and `UnknownDeviceKey` stay path-free so `get-config` can reuse them. |
| `DeviceConfigError`, `UnknownDeviceKey`, `InvalidDeviceValue`, `DeviceKeyNotASetting` | Spec: domain error values with one-line messages. |

**Not introduced:**

- an `env` field on `DeviceKey`;
- a typed config object with attribute access (`config.ledger_path`);
- a shared `resolve_ledger()` helper for the TUI and `env.py`;
- a separate `_DeviceCommand` base class;
- a `config` command group;
- a key-scoped `render` hook;
- a duplicate-key rule.

---

## 12. Alternatives rejected

- **The registry in `kohle/use_cases/` beside `settings.py`.** `connection.py`
  and `env.py` would have to import a use case to resolve the ledger, which
  reverses the layering.
- **The registry in `kohle/db/`.** The spec expects device keys from sampling
  and budgeting, which are not database concerns.
- **A top-level `kohle/config.py`.** It would belong to no layer in
  `AGENTS.md`.
- **One registry with a scope flag** (device keys in `SETTINGS`). The spec asks
  for a separate registry. The scopes differ in store, audit, input types and
  whether a value travels with the ledger.
- **The config check in the group callback.** Click runs it before parsing the
  subcommand's arguments, so `kohle-cli list-accounts --help` would fail on a
  bad file (AI §6.1).
- **`ledger_path()` reading the file itself on each call.** The file would be
  read several times per command (the check, `init`, the `list-settings`
  source), and `ledger_path` would have to return a `Result`. Every caller
  would handle errors that a single load already handled.
- **Loading the config at import.** It brings back the import-time state AI
  §4.1 removed. Tests set the environment after import, so they would read
  stale values.
- **A `_DeviceCommand` base and `_LedgerCommand(_DeviceCommand)`, opting out
  with `cls=`.** It works, but `cls=click.Command`, the AI §6.1 opt-out
  spelling, would then also skip the config check, silently. One class with a
  flag removes the reason to write `cls=`.
- **Skipping the config check when a factory is injected.** Then 056's
  behaviour could not be tested through the usual `obj=` path, and "every
  command" would hold only outside tests. The temp `XDG_CONFIG_HOME` makes it
  free.
- **An `env` field on `DeviceKey`.** The spec forbids new variables, so only
  `KOHLE_DB` could ever fill it. `KOHLE_DB` is used as given while file values
  are validated, so the field would need a converter too. That is two fields
  of generality for one fixed case.
- **Validating `KOHLE_DB` with the `ledger.path` validator.** It would change
  existing `KOHLE_DB` behaviour (relative paths, `~`), which the spec does not
  ask for. Its error also could not name a file (§14 item 3).
- **A partial config that ignores bad keys with a warning.** The spec requires
  a refusal.
- **A `config` subgroup (`config list`, `config get`).** Issue 057 asks for
  flat names, and grouping belongs to `cli-command-naming` (§3.1).
- **`config-list` / `config-get`.** They are flat, but noun-first, unlike every
  existing command except the reports.
- **`list-config` as a `tabulate` table.** It is heavy for one to four rows,
  and it could not share the source rendering with `list-settings` (§3.2).
- **Showing the file value that `KOHLE_DB` overrides.** The spec does not ask
  for it, and the source token is enough to diagnose the override.
- **A config-file line in `list-settings`.** The spec says "only ledger
  settings, the ledger path and the revision".
- **Carrying the source in `SettingsReport`.** That is a ledger use case, and
  the source is a device fact.
- **The device-key refusal inside `validate_settings`.** The use case would
  import the device registry and read `XDG_CONFIG_HOME` to name the file
  (§9.6).
- **The device-key refusal as a `KEY` argument callback**, so it would work
  with no ledger. It would run at parse time with Click's "Invalid value for
  'KEY'" wrapper and exit 2, not the spec's message.
- **`Path.expanduser`.** It raises on an unknown `~user` (Build vs. buy).
- **Treating `ledger.path = ""` as unset**, as an empty `KOHLE_DB` is. Writing
  the key in a file is explicit. Rejecting it is clearer than defaulting
  silently (§14 item 4).
- **Rejecting empty tables as unknown keys.** They configure nothing, and
  rejecting them would make `[ledger]` with every line commented out an error.
- **A duplicate-key rule for `"ledger.path"` beside `ledger.path`.** Quoting
  dotted segments in `_flatten` makes the case impossible.
- **`KOHLE_CONFIG`, per-key flags or per-key variables.** These are spec
  non-goals.

---

## 13. Issue mapping and per-slice files

**Order: 054 → 055 → 056 → 057 → 058.** 056, 057 and 058 each depend only on
055. They are linearised because all three edit `cli.py` and
`domain_errors.py`, and because 057 introduces `_with_source`, which 058 uses.

**Ordering with the `init.rc` → `init.toml` change.** Either can land first.
This feature only replaces `_init_file_path()`'s body with
`config_dir() / "init.toml"`. If the rename lands second, it finds that line
already done. That change should also catch `UnicodeDecodeError` in
`_read_init_file`, which has the same latent traceback as §4.3, and fix
`SettingDiffers`'s "init.rc says" wording.

### 054: tests never read the real per-user config

Production changes: none. `XDG_CONFIG_HOME` has been redirected by the autouse
fixture since 047.

Tests:

- `tests/conftest.py`: `_no_real_user_paths` also sets `HOME` to
  `tmp_path / "home"`. Any `Path.home()` fallback or `~` expansion then lands
  in the temp dir. Tests that exercise the fallback still `setenv` their own
  `HOME`.
- `tests/test_real_user_paths.py` (new), described in §15.1.
- The `write_init_rc` fixture keeps working unchanged. The rename change
  renames it.

### 055: `ledger.path` selects the ledger

Production changes:

- `kohle/infrastructure/device_config.py` (new): `config_dir`, `config_path`,
  `DeviceKey`, `DEVICE_KEYS`, `_ledger_path_value`, `_default_ledger_path`,
  `_flatten`, `validate_device_config` (unknown keys skipped, §7.3),
  `DeviceConfig(path, values)`, `load_device_config` (missing file only, §7.3),
  `Source`, `Effective`, `effective`.
- `kohle/domain/domain_errors.py`: `DeviceConfigError`, `InvalidDeviceValue`,
  `BadConfigFile`.
- `kohle/db/connection.py`: `ledger_path(config)`.
- `kohle/app/cli/cli.py`: `_KohleCommand` replaces `_LedgerCommand`;
  `pass_device_config`; `init` and `migrate` use `opens_ledger=False` and
  `ledger_path(config)`; `_init_file_path` uses `config_dir()`.
- `kohle/app/tui/tui.py`, `kohle/app/tui/widgets/table_editor/table_editor.py`
  (§8.1).
- `kohle/db/migrations/env.py` (§8.2).

Tests:

- `tests/conftest.py`: a `write_config(content) -> Path` fixture that writes
  `$XDG_CONFIG_HOME/kohle/config.toml`.
- `tests/test_ledger_location.py`: calls become
  `ledger_path(load_device_config().unwrap())`.
- `tests/test_cli.py`: the two seams (§7.4).
- `tests/test_device_config.py` (new), described in §15.2.
- `tests/test_real_user_paths.py`: a positive assertion that the temp
  `config.toml` path was opened.

README: as in §10.

### 056: a bad `config.toml` stops every command except `--help`

Production changes:

- `kohle/infrastructure/device_config.py`: `UnknownDeviceKey` from
  `validate_device_config`; the `TOMLDecodeError`, `UnicodeDecodeError` and
  `OSError` clauses in `load_device_config`.
- `kohle/domain/domain_errors.py`: `UnknownDeviceKey`.

Tests: §15.3. README: as in §10.

### 057: `list-config` and `get-config`

Production changes:

- `kohle/infrastructure/device_config.py`: `DeviceConfig.found`.
- `kohle/app/cli/cli.py`: `list_config_cmd`, `get_config_cmd`, `_with_source`.

Tests: §15.4. Also add `list-config` to the invocations in
`tests/test_real_user_paths.py`. README: as in §10.

### 058: `list-settings` shows the source; `set-setting` refuses device keys

Production changes:

- `kohle/domain/domain_errors.py`: `DeviceKeyNotASetting`.
- `kohle/app/cli/cli.py`: `list_settings_cmd` and `set_setting_cmd`, as in
  §9.5 and §9.6.

Tests: §15.5. README: as in §10.

---

## 14. Gaps in the spec and issues, and points for the user

1. **Command names: spec against issue.** The spec says `config list` /
   `config get <key>`, and issue 057 says "Flat naming, as the existing
   commands". The design follows the issue: `list-config` / `get-config`
   (§3.1). If the spec's group was meant, the switch is local to 057.
2. **"Every command except `--help`" is read strictly.**
   - Both `kohle-cli --help` and `kohle-cli <command> --help` are exempt,
     matching AI §6.1.
   - `list-config` and `get-config` are not exempt. On a bad file they print
     the same one-line error as everything else, and that line names the file
     and the key.
3. **`KOHLE_DB` is not validated and not `~`-expanded,** unlike `ledger.path`.
   A relative `KOHLE_DB` still selects a cwd-relative ledger. That is today's
   behaviour and outside the spec. Changing it is a separate decision.
4. **`ledger.path = ""` is rejected** as not absolute. It is not treated as
   unset, although an empty `KOHLE_DB` is.
5. **`set-setting ledger.path …` on a missing or outdated ledger** reports
   the ledger problem first, because `set-setting` opens the ledger before its
   body runs. Only with a usable ledger does the user see "is a device key;
   edit …". A user who moved their ledger and reaches for `set-setting` is
   told "no ledger at <old path>; run `kohle-cli init`". Running `init` would
   create an empty ledger there; it would lose no data, but it would leave a
   stray file.
6. **`list-config` has a footer naming the file** (`file: <path>`, with
   `(not found)` when missing). The spec does not ask for it (§3.2).
7. **The device-key message's backticks are literal**:
   `` `ledger.path` is a device key; edit <path> ``. That follows the spec's
   text and the existing messages' style.
8. **Empty TOML tables are accepted silently** (`[ledger]` with nothing under
   it, or `[foo]`). They configure nothing.
9. **Issue 054's "no path under the real home is opened" cannot be tested
   literally.** The checkout and its `.venv` usually live under the home
   directory (`/home/hari/code/kohle/.venv`), and imports open files there.
   The test narrows to the real kohle config and data directories, captured at
   import, before any fixture runs (§15.1). That is the concern the issue
   names.
10. **Issue 054's first criterion is already met.** The autouse fixture has
    redirected `XDG_CONFIG_HOME` since 047. 054 adds the `HOME` redirect and
    the proof test.
11. **The `app-initialization` amendment appears done but uncommitted.** The
    working tree's `dev/specs/app-initialization.md` already has both
    amendments from the spec's Dependencies (two scopes; `ledger.path` in the
    resolution order and `XDG_CONFIG_HOME` / `HOME` "to find the init file and
    `config.toml`"). It also has `init.toml`. The user should commit that
    before implementation starts, as the spec requires.
12. **"Valid values" for `ledger.path` is a description** ("an absolute path,
    or one starting with ~"), not an enumeration. Future enumerated keys, such
    as a role, list theirs, as `state` does.
13. **`kohle-tui` still cannot start** (AI §12). Its config load is verified
    by review only.

---

## 15. Testing notes

### 15.1 Isolation (054, strengthened in 055 and 057)

`tests/conftest.py`'s autouse `_no_real_user_paths` sets `KOHLE_DB`,
`XDG_DATA_HOME`, `XDG_CONFIG_HOME` and now `HOME` to temp paths.

`tests/test_real_user_paths.py`:

- **At module import**, before any fixture runs, capture the real kohle
  directories:
  `Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kohle"`
  and the matching data directory.
- **Install one `sys.addaudithook`** that records `open` and
  `sqlite3.connect` events into a module-level list, only while that list is
  not `None`. Audit hooks cannot be removed, so the gate is what scopes it.
  For `sqlite3.connect`, strip `file:` and the query from URI-form names and
  unquote them before comparing.
- **The test:**
  1. write an `init.toml`;
  2. record while running `init`, then `list-accounts` with no `obj`, then
     `--help`, all through `CliRunner`;
  3. assert that no recorded path lies under either real directory.
- **055 adds:** the temp `$XDG_CONFIG_HOME/kohle/config.toml` is among the
  recorded opens. The redirect is then proven to be used, not just the real
  path avoided. The audit event fires before the open is attempted, so this
  holds with no file present.
- **057 adds:** `list-config` to the invocations.

### 15.2 `ledger.path` (055), `tests/test_device_config.py`

- **Validator:**
  - accepted: `/abs/kohle.db`;
  - expanded: `~/k.db` becomes `<HOME>/k.db`;
  - rejected, each with the expected text: `kohle.db`, `""`, `1`, `{}` and
    `~nosuchuser/k.db`.
- **Equivalence:** `[ledger]\npath = "/x"` and `ledger.path = "/x"` load to
  equal `values`.
- **The spec's four testables, with temp `XDG_CONFIG_HOME` and
  `XDG_DATA_HOME`.** Each is checked through `ledger_path(...)` and end to end
  through `CliRunner` with no `obj`. The ledger is made with `init`, which now
  builds at the resolved path.
  - `ledger.path` set, `KOHLE_DB` unset: `list-settings` names the
    `ledger.path` file.
  - Both set: `KOHLE_DB` wins.
  - Neither set: the XDG default.
  - `ledger.path = "kohle.db"`: `list-accounts` exits 1 naming the file and
    `ledger.path`.
- **`KOHLE_DB=""` with `ledger.path` set:** the file is used.
- **Missing config file:** commands run with the defaults, exit 0.
- **`ledger.path` naming a missing file:** `list-accounts` gives the existing
  ``no ledger at <that path>; run `kohle-cli init` ``.
- **Alembic env:**
  - with `ledger.path` set and `KOHLE_DB` unset,
    `command.upgrade(alembic_config(), "head")` upgrades the file at
    `ledger.path`;
  - with an invalid `ledger.path`, it raises `CommandError` whose message
    names the file.

### 15.3 A bad file (056)

- **The spec's testable:** with `ledgr.path = "/x"`, `list-accounts` exits
  non-zero and the output contains the config path and `ledger.path`.
  `kohle-cli --help` and `kohle-cli list-accounts --help` exit 0.
- **One line each, with no `Traceback`, naming the file:**
  - an invalid value (lists the expected form);
  - a TOML syntax error;
  - non-UTF-8 bytes;
  - a directory at the `config.toml` path.
- **Flattening:**
  - `"ledger.path" = "/x"` is an unknown key, shown as `'"ledger.path"'`;
  - `ledger.path = {}` and `[ledger.path]` are invalid values;
  - `[ledger]` with nothing under it gives defaults and exit 0.
- **Covers `init` and `migrate`:**
  - `init` with a good `init.toml` and a bad `config.toml` exits 1, and
    neither the file at `KOHLE_DB` nor its parent directory exists;
  - `migrate` on a behind ledger with a bad config exits 1, and the ledger's
    bytes are unchanged.
- **Nothing is written with an injected factory:** `add-account` with
  `obj=session_factory` and a bad config exits 1, with zero `Account` and
  `OperationGroup` rows.
- **Structural:** every value in `cli.commands` is an instance of
  `_KohleCommand`.

### 15.4 `list-config` and `get-config` (057)

- **No file:** `ledger.path = <XDG default>  (default)` and
  `file: <path> (not found)`.
- **File set:** `(file)`, with `~` shown expanded. **`KOHLE_DB` set:**
  `(KOHLE_DB)`.
- **The spec's testable:** with `ledger.path` pointing at a nonexistent file,
  `list-config` exits 0 and shows the path.
- **`get-config ledger.path`** prints exactly the path and a newline.
- **Behind and ahead ledgers** (built as in `test_schema_check.py`):
  `list-config` exits 0.
- **Never opens the ledger:** with `kohle.app.cli.cli.open_ledger`
  monkeypatched to raise, both commands exit 0. The audit hook records no
  `sqlite3.connect` during either.
- **`get-config nope`** exits 1 and lists `ledger.path`.

### 15.5 `list-settings` and `set-setting` (058)

- **After `init`, the path line's suffix:**
  - `KOHLE_DB` set: it ends `(KOHLE_DB)`;
  - `ledger.path` only: `(file)`;
  - neither: `(default)`.

  `test_init_then_list_accounts_and_list_settings`'s existing `in` assertion
  keeps passing.
- **Injected in-memory factory:** the line is exactly `ledger:   (in memory)`.
- **`set-setting ledger.path /x`** with `obj=session_factory` exits 1. The
  output contains `` `ledger.path` is a device key; edit `` followed by the
  temp config path. `Setting`, `Operation` and `OperationGroup` counts are
  unchanged.
- **Ledger keys as before:** `set-setting foo x` still gives `UnknownSetting`
  listing `state`, and `set-setting state HE` still succeeds.
