# Design: Price fetcher plugin

Spec: `dev/specs/price-fetcher-plugin.md` (frozen)
Issues: `dev/issues/029`–`034`

Layering per `AGENTS.md` stays `app -> use_cases -> services ->
infrastructure/domain`. Only services touch a `Session`. Functions return
`Result[T, E]`; domain and plugin errors are `Exception` subclasses used as
values.

> **Status: not blocked.** The first pass's slicing adjustments and the
> unrequested-symbol rewording (§14.1, §14.3, §14.4) have since been adopted
> into issues 030 and 031. Issue 033 now also requires oldest-close-first
> request ordering, which is built in §6.4. Alpha Vantage facts are
> split into what was verified first-hand on 2026-10-11 and what is inferred
> (§10.2). No part of the design depends on an inferred fact being true.

---

## 1. Summary of the shape

| File | Change | Issue |
|---|---|---|
| `kohle/plugin/price_plugin.py` | **new** contract: `PriceFetcherPlugin`, `Close`, `Unavailable`, `UnavailableReason`, `PriceResult`, `PriceFetchError`, `MissingEnvironmentVariable` (§2) | 029 |
| `kohle/plugin/plugin_manager.py` | private `_load(kind)`; `load_plugins()` keeps its signature and returns importers only; new `load_price_plugins()`; the `f`-string fix (§3) | 029 |
| `kohle/domain/models.py` | new `PriceBinding` (029); `Price` constraint becomes `uq_price_unit_date`, `__eq__` follows it, docstring corrected (030) | 029, 030 |
| `kohle/domain/domain_errors.py` | `PriceError` family, per-unit rejection errors, three aliases; `NotASecurityUnit.__str__` made kind-neutral (§12, Error propagation) | 029–031 |
| `kohle/services/price_services.py` | **new**: binding upsert and lookup; price add, exists and latest (§5.3, §6.6) | 029, 030 |
| `kohle/use_cases/journal.py` | new `held_units(ctx)` beside `account_balance` (§6.2) | 030 |
| `kohle/use_cases/prices.py` | **new**: `SetPriceSource`, `ListPriceTargets`, `oldest_close_first`, `call_price_plugins`, `AppendPrices`, the outcome types, `validate_close`, `latest_close` (§5–§8) | 029–033 |
| `kohle/app/plugins/kohle_file_price_fetcher.py` | **new**: `FilePriceFetcher`, name `file` (§9) | 030 |
| `kohle/app/plugins/kohle_alphavantage_price_fetcher.py` | **new**: `AlphaVantagePriceFetcher`, name `alphavantage` (§10) | 033 |
| `kohle/app/cli/cli.py` | `set-price-source UNIT PLUGIN SYMBOL` (029), `fetch-prices` (030) | 029, 030 |
| `pyproject.toml` | entry points `file` (030) and `alphavantage` (033). **No new dependency** (§10.4) | 030, 033 |
| `alembic/versions/` | **two** migrations, one per schema-bearing slice (§4) | 029, 030 |
| `tests/fixtures/alphavantage/` | **new**: recorded response bodies (§10.6) | 033 |
| `README.md` | the two commands, and a "Writing price plugins" section beside the importer one | 029–033 |

**Import direction.** `use_cases/prices.py` imports the contract from
`kohle/plugin/price_plugin.py`, as `journal.py` imports the importer contract.
That only works because the contract module is a leaf: it imports nothing from
kohle but `kohle.core.result`. It must stay that way, for the reason the
importer design gives (`importer-plugins-for-assets.md` §1). Otherwise every
third-party price plugin would depend on the services layer.

**Nothing on the recording or import path changes**, with one exception:
`journal.py` gains `held_units`. It is a read over journal lines and refers to
no price type, and the guard test (§11) holds it to that.

---

## 2. The contract (decision 1)

### 2.1 The module

```python
class PriceFetchError(Exception):
    pass


class MissingEnvironmentVariable(PriceFetchError):
    def __init__(self, variable: str) -> None: ...
    def __str__(self) -> str: ...          # "KOHLE_PRICE_FILE is not set"


class UnavailableReason(Enum):
    no_symbol = "no_symbol"
    not_covered = "not_covered"
    transient = "transient"


@dataclass(frozen=True, slots=True, kw_only=True)
class Close:
    price_date: date
    price: Decimal
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Unavailable:
    reason: UnavailableReason
    detail: str

    def __str__(self) -> str: ...          # f"{reason.value}: {detail}"


PriceResult = Close | Unavailable


class PriceFetcherPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def fetch_latest_closes(
        self, symbols: Sequence[str]
    ) -> Result[dict[str, PriceResult], PriceFetchError]: ...
```

### 2.2 Decisions in that block

- **`frozen`, `slots`, `kw_only`.** The spec requires them, and they match
  `CashRow` / `SecurityRow`. `kw_only` is what stops
  `Close(price_date, price, currency)` being built in the wrong order by a
  third-party author who never runs mypy.
- **No defaults on any field.** This is the `CashRow` rule: a plugin states
  the currency every time, so binding a symbol as an EUR assertion (spec,
  accepted risk) has a visible line in the plugin that makes the assertion.
- **`price_date`, not `date`.** It matches `Price.price_date`, and a field
  named `date` would shadow the type inside the class body. This is the same
  reasoning as `CashRow.entry_date`.
- **`currency: str`, not an enum.** Core compares it with `BASE_CURRENCY`,
  which is a `str` (§7). An enum would force the contract module to list
  currencies, and listing them is exactly what the FX Non-Goal leaves out.
- **`UnavailableReason` is an `Enum`**, in house style (`UnitKind`,
  `AccountType`). The three values mean:
  - `no_symbol`: the source's own data has no entry for the symbol, as with
    the file plugin when a row is missing. The fix is the user's data or
    binding.
  - `not_covered`: the provider does not carry the instrument. The fix is a
    binding to another plugin.
  - `transient`: a later run may succeed, after throttling or before the
    first finished close of a new listing.
- **`Unavailable.detail` is an addition to the spec's shape.** The spec has
  the reason only. The detail exists because of one verified case. Alpha
  Vantage sends its daily-quota notice, its per-second burst notice and its
  premium-endpoint notice under the same `"Information"` key (§10.2), and all
  three map to `transient`. Without the provider's text, a premium-only
  endpoint would show up as "transient" on every run forever, and nothing
  would tell the user why. `__str__` makes an `Unavailable` print the same
  way as an error, so the CLI renders every unpriced reason with `str()`.
- **The per-symbol result is `dict[str, PriceResult]`, keyed by the symbol
  exactly as requested.** It is a dict and not a list aligned with `symbols`,
  because with an aligned list an off-by-one in a plugin silently gives one
  unit another unit's close. That is the wrong-number-with-no-error failure
  this codebase keeps designing out. Under a dict, a missing key and an
  extra key are both detectable, and core reports both (§6.6).
- **The parameter is `Sequence[str]`, and order matters.** A throttled source
  works through symbols in the given order (§2.3 rule 6). Core passes them
  oldest stored close first (§6.4), so a limited quota is spent on the
  stalest prices, and which symbols a throttled run covers is deterministic
  and testable. Symbols arrive distinct (§6.3).
- **`MissingEnvironmentVariable` lives in the contract** for the reason
  `StatementUnreadable` does: both bundled plugins need it (spec: "a missing
  API key or file-path variable" is a named plugin error), and a third-party
  plugin should not have to invent its own.

### 2.3 Rules the contract docstring states

1. **`Err` means the plugin as a whole could not run.** That covers missing
   configuration, an unreachable source and an unreadable or malformed file.
   Anything that concerns one symbol is an `Unavailable` value.
2. **Expected failures are never raised.** A plugin converts I/O, network and
   parse failures at the one place each happens, catching explicit types.
   **A plugin bug is not caught by core** (§12, Error propagation).
3. **Only finished daily closes.** A trading day still in progress is never
   returned.
4. **No I/O and no configuration reads in `__init__` or at module import.**
   Every plugin-using command imports every entry point's class (§3.3), and
   `set-price-source` instantiates every price plugin to learn their names.
   If the file plugin read `KOHLE_PRICE_FILE` in `__init__`, a user binding a
   unit to `alphavantage` would hit an error about a file variable they never
   set. Configuration is read when `fetch_latest_closes` runs, and its
   absence is that call's `Err`.
5. **No state between calls**, as for importers.
6. **Requests are spent in the order given.** A plugin that cannot serve
   every symbol in one call (a quota, a rate limit) works through `symbols`
   in order and returns `Unavailable(transient)` for each symbol it did not
   reach. It never re-sorts. Core orders the symbols oldest stored close first
   (§6.4), and this rule is what turns that order into a fair use of a
   limited quota. A plugin with no limit can ignore the order.

---

## 3. Plugin discovery by kind (decision 2)

### 3.1 How a plugin declares its kind

**By subclassing.** A class registered under `kohle.plugins` is an importer
if it subclasses `StatementImporterPlugin`, and a price fetcher if it
subclasses `PriceFetcherPlugin`. No metadata field, no naming convention and
no second entry-point group are needed. The spec keeps one group, and the
ABC is already the thing the plugin author must implement.

### 3.2 The API

```python
def load_plugins() -> dict[str, StatementImporterPlugin]: ...       # unchanged signature
def load_price_plugins() -> dict[str, PriceFetcherPlugin]: ...       # new
def _load(kind: type[P]) -> dict[str, P]: ...                         # the one loop
```

- **`load_plugins()` keeps its name, signature and meaning.** It returns
  importers only. `import_statement` and `list_importer_plugins` in `cli.py`
  do not change, and nor do the two tests that monkeypatch
  `kohle.app.cli.cli.load_plugins` with a lambda returning a dict. That is the
  caller's constraint, met with no edit at any existing call site.
- **`_load(kind)`** iterates `entry_points(group="kohle.plugins")` and loads
  each class. Then:
  - A class that is **neither** kind: still `TypeError`, now naming both
    ABCs. That is a broken installation, and it should stop every
    plugin-using command, as it does today.
  - A class of the other kind: skipped, and **not instantiated**.
  - A class of this kind: instantiated, then checked for a duplicate
    `instance.name` **within this kind**. Names are looked up per kind, so an
    importer and a price plugin that share a name are unambiguous.
- **The duplicate-name `ValueError` gets its `f` moved outside the string.**
  The spec asks for this fix.
- `cli.py` imports `load_price_plugins` into its own namespace, so the CLI
  tests for the price commands monkeypatch `kohle.app.cli.cli.load_price_plugins`
  just as the importer tests patch `load_plugins`.

### 3.3 A consequence, recorded

A class's kind can only be read after it is loaded, so `import-statement` now
**imports** the price plugin modules, though it never instantiates or calls
them. That is why contract rule 4 forbids side effects at import. It does not
breach "the import path contains no reference to price plugins": the
reference is in the shared loader, which the spec mandates, not in import
code. §11 states exactly what the guard test checks.

---

## 4. Schema and migrations (decision 5)

### 4.1 Two migrations, one per schema-bearing slice

The classification and splitting designs set the precedent. Each slice that
changes the schema upgrades and downgrades on its own, the chain stays linear,
and there is no Alembic branch.

| slice | migration | adds / changes | downgrade |
|---|---|---|---|
| 029 | `<rev>_price_bindings.py`, `down_revision = 'a1cebfe54f33'` | `price_bindings` table | refuse if any binding exists; else drop |
| 030 | `<rev>_prices_unique_per_day.py`, `down_revision = <029's rev>` | `prices`: `uq_price_unit_date_source` → `uq_price_unit_date` | restore the old constraint; **no refusal**, because it is lossless |

**Why not one migration.** The issues give the binding table to 029 and the
uniqueness change to 030. One migration in 029 would ship 030's constraint a
slice early, and the `Price` model (which `create_all` builds for every test)
would disagree with the database until 030 landed. The spec allows "the same
migration or one beside it". The cost is a one-word deviation: the 030
migration is off 029's revision, not `a1cebfe54f33` (§14.4).

### 4.2 `price_bindings` (029)

```python
class PriceBinding(base):
    __tablename__ = "price_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    plugin_name: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (UniqueConstraint("unit_id", name="uq_price_binding_unit"),)
```

- **A surrogate `id` rather than `unit_id` as the primary key.** `crud_create`
  and `crud_update` record `entity.id` in the `Operation`, and every table
  here has one.
- **Not `Archivable`.** No code path soft-deletes a binding, and a
  soft-deleted row would still hold the unique `unit_id` slot. `deleted_at`
  would be a column whose only possible non-null value is a bug. `Price`, the
  sibling table, is not `Archivable` either.
- **No `unit` relationship.** Nothing traverses it. `Classification`'s
  comment states the house rule: an unused relationship is a lazy load
  waiting to fire after the session closes.
- **No currency column** (spec).
- Migration: plain `op.create_table`. A new table needs no batch mode.
  `downgrade()` opens with a `_refuse_if_unrepresentable()` that counts rows
  first and raises `RuntimeError` naming the count. That is the refusal
  standard in `expense-splitting.md` §10.3: bindings are user declarations
  the ledger cannot reconstruct.

### 4.3 `prices` uniqueness (030)

```python
with op.batch_alter_table("prices") as batch:
    batch.drop_constraint("uq_price_unit_date_source", type_="unique")
    batch.create_unique_constraint("uq_price_unit_date", ["unit_id", "price_date"])
```

and the mirror image in `downgrade()`.

- **Batch mode is required.** SQLite cannot `ALTER` a constraint, and the
  splitting design already found that `op.*` constraint operations raise
  `NotImplementedError` there. **Verified in this venv** (Alembic 1.18.3 /
  SQLAlchemy 2.0.46 / SQLite 3.45.1), with a table shaped exactly like
  `7f3c1d9a2b40`'s `prices`:
  - The named constraint is found by reflection and replaced.
  - A pre-existing row survives the rebuild.
  - A second `(unit, date)` with a different `source` is then refused with
    `UNIQUE constraint failed: prices.unit_id, prices.price_date`.
  - The downgrade restores `uq_price_unit_date_source`.
- **The downgrade has no refusal, because it loses nothing.** Every row set
  that satisfies `(unit_id, price_date)` also satisfies `(unit_id,
  price_date, source)`, so restoring the wider constraint always succeeds.
  Refusing would make the round trip fail for no reason.
- **The upgrade has no duplicate pre-check, because none can exist.** No code
  path has ever written to `prices` (the table was created in `7f3c1d9a2b40`
  with no writer). The live `kohle.db` was checked read-only: it is at
  `a1cebfe54f33` with **0** rows in `prices`. A pre-check would be error
  handling for an impossible case. Even a hand-inserted duplicate would fail
  loudly, with SQLite's own message.
- **The model changes in the same slice.** `Price.__table_args__` gets
  `UniqueConstraint("unit_id", "price_date", name="uq_price_unit_date")`, and
  `Price.__eq__` drops `source`, so that equality is the new identity. The
  docstring's "Written by price plugins" becomes "written by `fetch-prices`
  from plugin results": plugins never write, core does.
- `source` stays a column and holds the plugin name (spec). **It does not
  record the symbol.** After a rebind from `X` to `Y` on the same plugin,
  history cannot say which symbol produced an older row. The spec's binding
  has no history either, so this is recorded rather than built.

### 4.4 `tests/test_migration_downgrade.py`

- `test_upgrade_creates_the_ledger_tables` keeps passing unchanged, since
  `prices` still exists.
- New constants, in the file's existing style:
  `BEFORE_PRICE_BINDINGS = "a1cebfe54f33"` and
  `BEFORE_PRICES_UNIQUE_PER_DAY = <029's rev>`.
- New tests:
  - `price_bindings` round-trips when empty.
  - The downgrade refuses with one binding and leaves the table in place.
  - At head, a second `(unit, date)` row with another `source` is refused.
    After downgrading to `BEFORE_PRICES_UNIQUE_PER_DAY` the same insert
    succeeds, and re-upgrading with only one row per day succeeds.

---

## 5. `set-price-source` (issue 029)

### 5.1 The command

```
kohle-cli set-price-source UNIT PLUGIN SYMBOL
```

`set_price_source_cmd`. Click 8.3.1 strips the `_cmd` suffix, which was
verified in this venv: `fetch_prices_cmd` becomes `fetch-prices`. The command
calls `SetPriceSource(make_session()).execute(unit, plugin, symbol,
sorted(load_price_plugins()))` and prints `Price source for UNIT:
PLUGIN SYMBOL`.

### 5.2 `SetPriceSource`

```python
class SetPriceSource(UnitOfWork[PriceBinding, SetPriceSourceError]):
    def execute(
        self, identifier: str, plugin_name: str, symbol: str, available_plugins: Collection[str]
    ) -> Result[PriceBinding, SetPriceSourceError]: ...
```

In order: every check that needs no database comes before the first read,
which is the `ImportStatement` ordering rule.

1. `symbol.strip()` empty → `EmptyPriceSymbol`. The spec does not list this
   case, but `""` is a reachable CLI argument and `AddUnit` refuses an empty
   identifier for the same reason. Stripping is not guessing; case is left
   alone.
2. `plugin_name not in available_plugins` →
   `UnknownPricePlugin(plugin_name, sorted(available_plugins))`. The message
   names them, as the spec requires, or says none are installed.
3. `get_unit_by_identifier_service` → `UnitNotFoundError`, reused.
4. `unit.kind != UnitKind.security` →
   `NotASecurityUnit(identifier, unit.kind.value)`, reused (§12, Error
   propagation, for its reworded message).
5. `set_price_binding_service(ctx, unit.id, plugin_name, symbol)`.

**The plugin check lives in the use case**, which receives the installed
names, rather than in the CLI as `import_statement`'s `"Plugin not found"`
does. That keeps all four refusals in one place, all four testable without
`CliRunner`, and all four as named `__str__`-bearing errors. The use case
sees names, never plugin objects, so it stays plugin-agnostic.

**A unit does not have to be held to be bound.** Binding before buying is
legitimate, and the spec does not ask for a check.

### 5.3 The upsert

`set_price_binding_service` follows `set_split_adjusting_entry_service`, the
established insert-or-update shape:

- `price_bindings_service(ctx, [unit_id])` finds the existing row, if any.
- **None:** `_create_price_binding_service` (`@crud_create`).
- **Same plugin and symbol:** return it, **with no write.** This is the house
  rule that a replay leaves no `OperationGroup` (`AGENTS.md`;
  `importer-plugins-for-assets.md` §4.2 step 5). Re-running the same
  `set-price-source` is invisible in `list-operations`.
- **Different:** `_update_price_binding_service` (`@crud_update`) sets both
  columns. This is how a mistyped symbol is fixed, or a unit moves source.

**Rebinding replaces in place, and the old binding is not kept.** The
`Operation` records that an update happened, not what the values were. This
is the same limitation as `set_split_group_service`, because `_record_write`
never fills `Operation.field` / `state`. The spec asks for replacement and no
history.

**Two units may be bound to the same `(plugin, symbol)`.** The spec is silent
on this (§14.6). Nothing refuses it, and fetching handles it (§6.3).

---

## 6. `fetch-prices` (issues 030, 031; decision 6)

### 6.1 The flow

```
fetch-prices
  1. ListPriceTargets   UnitOfWork, reads only       -> PriceTargets, grouped and in request order
  2. call_price_plugins no session, no transaction  -> FetchedCloses
  3. AppendPrices       UnitOfWork, one transaction -> FetchReport
  4. CLI renders one row per held security; exits non-zero if any is Unpriced
```

This is the spec's structure, two `UnitOfWork`s with the plugins called
between them, in the precedent `import_statement` set: **no plugin runs while
a transaction is open.** The step-1 transaction commits, writes nothing and
leaves no `OperationGroup`, before any network call.

**Placement differs slightly from the precedent (§14.5).** Step 2 is a
function in `use_cases/prices.py`, not a loop written inline in the CLI. It
does more than call: it asks each plugin once, and it turns a binding whose
plugin has since been uninstalled into a per-unit reason. That reason has to
come out the same from any frontend. The CLI is left with wiring and
rendering, as for every other command.

### 6.2 Held units: `held_units(ctx)` in `journal.py`

```python
def held_units(ctx: DbTransactionContext) -> Result[list[Unit], BalanceError]
```

`list_accounts_service` gives every account id (it applies no `deleted_at`
filter, which was checked, so lines on any account count).
`account_lines_service` loads their lines, with `unit` already joined-loaded.
`aggregate_by_unit` folds them, and the result is the units whose
`quantity != 0`, mapped back to their `Unit` objects from `line.unit`.

- **The spec names this fold.** It is "the same fold `aggregate_by_unit`
  performs per account, applied across all accounts". Reusing the function is
  the only way to guarantee that.
- **Folded in Python with `Decimal`, never with SQL `SUM`. This is
  load-bearing, and it was verified.** On SQLite, `Numeric(20, 8)` columns are
  stored as `REAL`. `SUM` of `0.1 + 0.2 − 0.3` returns `2.78e-17`, so a
  sold-out fractional position, which is routine with ETF savings plans,
  would be "held" for ever. Read back through SQLAlchemy, the same values are
  `Decimal`s quantised to 8 places, and their sum is exactly 0.
- **Kind-agnostic.** "Held" is a ledger fact, and "security" is this
  feature's filter, applied in `ListPriceTargets`. Portfolio reporting
  ("holdings times latest price") will need the same definition of held for
  every kind, including commodities once they are in scope.
- **In `journal.py`, beside `account_balance`.** The fold and account
  enumeration are journal concerns, and `prices.py` should not know how a
  position is computed. It refers to no price type, so the §11 guard test
  still holds for `journal.py`.
- Cost: one load of every journal line. At personal-ledger scale that is the
  same order as one `net-worth` call.

### 6.3 `ListPriceTargets` and `PriceTargets`

```python
@dataclass(frozen=True, slots=True)
class PriceTargets:
    # plugin name -> symbol -> the held units bound to that (plugin, symbol)
    by_plugin: dict[str, dict[str, list[Unit]]]
    # plugin name -> its symbols in the order to request them (§6.4, issue 033)
    request_order: dict[str, list[str]]
    unbound: list[Unit]


class ListPriceTargets(UnitOfWork[PriceTargets, ListPriceTargetsError]):
    def execute(self) -> Result[PriceTargets, ListPriceTargetsError]: ...
```

- `held_units`, then filter to `UnitKind.security`, then one
  `price_bindings_service(ctx, unit_ids)` call. Each held security goes to
  `by_plugin[binding.plugin_name][binding.symbol]`, or to `unbound`.
- **Symbol to units is one-to-many.** If two units share a binding (§5.3),
  the symbol is requested once and the close applies to both. No unit is
  silently dropped, and no plugin is asked twice for one symbol.
- **Grouping is by binding, with no fallback** (spec). A unit appears under
  exactly one plugin or in `unbound`.
- **The request order (issue 033).** `latest_price_service` is called for
  each bound held unit, and `oldest_close_first` once per plugin fills
  `request_order` (§6.4). Until 033 lands, the field does not exist and
  `call_price_plugins` passes `sorted(symbols)`.

### 6.4 Request order: oldest stored close first (issue 033)

```python
def oldest_close_first(stored: Mapping[str, Sequence[date | None]]) -> list[str]
```

**(d) Name, location, signature.** A pure function in `use_cases/prices.py`,
beside `validate_close`. `stored` maps each symbol a plugin will be asked for
to the latest stored close date of **each** unit bound to it, with `None` for
a unit that has no stored close. It returns those symbols in the order the
plugin should spend its requests:

1. A symbol's staleness is the **oldest** of its units' dates. A `None` is
   older than any date.
2. Symbols whose staleness is `None` come first, then the rest by
   staleness, oldest first.
3. Equal staleness breaks by symbol, ascending.

**Why it exists.** With more symbols than a run's quota, a fixed order
starves a fixed tail. Under the first pass's alphabetical order, more than
about 25 symbols bound to `alphavantage` meant the same alphabetical tail was
`transient` on every run, for ever. That failure was loud (exit 1 every day,
then stale in reporting) but permanent. Issue 033 now requires the gap to
stay bounded.

**(a) Ordering happens in core, before the call, and the plugin preserves
it.**

- **Only core can order by stored close.** The contract module is a leaf, so
  a plugin cannot read the ledger (§1), and it does not need to: the contract
  already takes a `Sequence`, which is ordered.
- **Preserving the order is contract rule 6 (§2.3).** The Alpha Vantage
  plugin already behaves this way (§10.3). It requests `symbols[0]`,
  `symbols[1]` and so on, and at the first `"Information"` body it marks
  `symbols[i:]` transient. So the symbols a throttled run leaves unpriced are
  always the *freshest* ones, and that is what makes the order rotate.
- **The same order goes to every plugin.** Core does not know which plugins
  have a quota. Naming `alphavantage` in core would break the spec's
  plugin-agnosticism, which §11's third-plugin test holds. For `file` the
  order is harmless.
- **`request_order` is an explicit field, not the insertion order of
  `by_plugin`'s inner dict.** Python dicts do keep insertion order, but then
  the quota policy would rest on an invisible property. One `sorted()` added
  for display would silently undo it, and the only symptom would be
  staleness days later. As its own list it is visible, typed and asserted by
  a test. `by_plugin` stays the symbol-to-units map `AppendPrices` uses.
- **The price table is the rotation state.** No cursor and no "last
  requested" column is persisted. Each unit's latest stored close already
  records when it was last refreshed. A second record of the same fact could
  disagree with it, for example after a run whose append failed.
- **Staleness is about stored history, not its source.** After a rebind from
  `file` to `alphavantage`, the unit's closes from `file` still count.
- **The reads.** `ListPriceTargets` calls `latest_price_service` for each
  bound held unit: one small query per unit, inside the read-only
  transaction. `AppendPrices` still reads `previous` itself, in its own
  transaction, because `previous`, the existence check and the insert must
  describe the same state.

**(b) A symbol bound to several units takes the oldest of their dates.** The
unit that most needs a refresh decides. A unit with no stored close at all
(newly bought, or newly bound) therefore puts its symbol first, even when the
other unit on that binding was priced yesterday. The cost is at most one
request the other unit did not need, and only until the first fetch gives
both units the same close.

**(c) Ties break by symbol.** Ties are the normal case: after a run, every
symbol refreshed in it has the same latest date. A deterministic tie-break
makes the order, and so which symbols a throttled run reaches, reproducible
in tests. The tie-break is the symbol, not a unit identifier, because the
symbol is what is requested and is unique within one plugin's request. Two
units sharing a symbol would make a unit-identifier tie-break ambiguous.

**(e) The bound.** Take N distinct symbols bound to a plugin that can serve Q
of them per run. On Alpha Vantage's free tier Q is about 25 a day, if nothing
else uses the key. Each run refreshes the Q stalest symbols, which then move
to the back of the next run's order. With one run a day, every symbol is
refreshed at least once every ⌈N/Q⌉ runs, so the gap between the freshest
and the stalest stored close stays at about ⌈N/Q⌉ days:

- N = 30: every symbol at most 2 days behind, where alphabetical order left
  5 symbols unpriced on every run;
- N = 60: 3 days;
- N ≤ Q: every symbol every run, and the order changes nothing.

The finished-day guard's one-day lag (§10.1) shifts every symbol alike, so it
does not widen the gap.

What the bound assumes, stated so it is not read as a guarantee:

- **One run a day that spends the whole quota.** A second run the same day
  gets no new free quota, and a key shared with other tools shrinks Q.
- **Each request yields a newer close.** A weekend or holiday run can request
  symbols whose newest close is already stored. `already stored` does not
  advance a symbol's date, so those symbols stay at the front, and the
  rotation pauses for a day rather than skipping anyone.
- **Every symbol eventually gets a close.** A symbol that never does (because
  it is `not_covered`, `no_symbol`, or wrongly bound) has no stored close.
  It is first in every run and costs one request a day until it is rebound.
  That is loud, since the unit is unpriced and the run exits 1 every day, and
  each such binding reduces Q by one.

### 6.5 `call_price_plugins`

```python
FetchedCloses = dict[str, Result[dict[str, PriceResult], PriceFetchError | UnknownPricePlugin]]

def call_price_plugins(
    targets: PriceTargets, plugins: Mapping[str, PriceFetcherPlugin]
) -> FetchedCloses: ...
```

For each plugin name in `targets.by_plugin` (sorted):

- **Installed:** call `fetch_latest_closes(targets.request_order[name])`
  once, passing the list unchanged (§6.4). Before 033 it is
  `sorted(symbols)`. That one call is the spec's "each plugin is asked only
  for its own symbols, once per run".
- **Not installed** (bound earlier, then uninstalled or renamed):
  `Result.err(UnknownPricePlugin(name, sorted(plugins)))`. `AppendPrices`
  then treats it exactly like a plugin's own `Err` (§6.6), so every unit
  bound to it ends unpriced and the run exits non-zero.

Plugins are called sequentially. There is no concurrency (§12).

### 6.6 `AppendPrices`, and per-unit atomicity

```python
class AppendPrices(UnitOfWork[FetchReport, PriceError]):
    def execute(
        self, targets: PriceTargets, fetched: FetchedCloses, today: date
    ) -> Result[FetchReport, PriceError]: ...
```

Inside the one transaction:

1. Every `targets.unbound` unit → `Unbound`.
2. For each plugin in `targets.by_plugin`, taking its `fetched[name]`:
   - **`Err(e)`:** every unit bound to the plugin → `Unpriced(reason=e)`.
     Nothing is written for them, and other plugins carry on.
   - **`Ok(results)`:** every key in `results` that was not requested →
     `UnrequestedSymbol(name, key)` in `report.ignored` (§14.3). Then, for
     each requested symbol:
     - Absent from `results` → `Unpriced(MissingCloseResult(symbol))`.
     - `Unavailable` → `Unpriced(that Unavailable)`.
     - `Close` → `validate_close(close, today)` (§7). On a rejection:
       `Unpriced(rejection)`. Otherwise, for each unit bound to the symbol:
       - `price_exists_service(ctx, unit.id, close.price_date)`. If it is
         true → `AlreadyStored`.
       - Otherwise, `latest_price_service(ctx, unit.id)` gives the previous
         close, `add_price_service(ctx, unit.id, close.price_date,
         close.price, source=name)` writes the new one, and the outcome is
         `Priced`.
3. `Ok(FetchReport(outcomes sorted by unit identifier, ignored))`.

A service `Err` in step 2 (the database failing) returns `Err`, which rolls
back the whole append.

**How "one unit's failure must not roll back another's close" holds:**

- **Every per-unit failure the spec names is a value, decided before that
  unit's write.** That covers an `Unavailable`, a plugin `Err`, an
  uninstalled plugin, a missing result, a validation failure and "already
  stored". None of them becomes the transaction's `Err`, so none can roll
  anything back. Each becomes that unit's outcome, and the loop moves on.
- **Each unit's write is one row**, so "nothing partial is written for it"
  holds trivially.
- **The only things that roll back the append are a service `Err` and an
  exception at the `BLE001` seam.** A service `Err` means the database
  failed. An exception means a bug. Neither is a unit's failure: a locked or
  full database fails every unit alike. Rolling back the whole run in those
  cases is the existing `DbTransaction` contract, and it is the safe outcome.
- **The duplicate check must come before the insert, in the same
  transaction. It cannot be left to the constraint.** This was verified
  against `DbTransactionContext.run` with the real models. After one
  `UNIQUE` violation, *every later write in that transaction* fails with
  `PendingRollbackError` ("This Session's transaction has been rolled
  back..."). Insert-and-catch would therefore turn one already-stored day
  into a failure of the whole run. Check-then-insert is also the established
  pattern (`existing_references_service` before `post_entry`).
- **The constraint stays as the backstop.** The only way to reach it is a
  concurrent `fetch-prices` inserting the same `(unit, date)` between the
  check and the insert. That run's append fails whole, with SQLite's message,
  and writes nothing. Re-running reports "already stored". This is recorded,
  not handled (§12, Concurrency).

**Audit trail.** Every new row goes through `add_price_service`
(`@crud_create`). So a run that writes anything leaves **one**
`OperationGroup` with one `create prices <id>` per new close, which is how
`list-operations` should read: "this fetch added these closes". A run that
writes nothing, such as the second of two back-to-back runs, makes no write
call and leaves no group. The lazy group creation in `DbTransactionContext`
already gives that, so "running twice writes nothing the second time" also
holds for the audit trail.

The rejected structures (insert-and-catch, `SAVEPOINT` per unit, one
`UnitOfWork` per unit) are in §12, Alternatives rejected, with their reasons.

### 6.7 The outcomes

```python
@dataclass(frozen=True, slots=True)
class Priced:
    unit: Unit
    plugin_name: str
    symbol: str
    close: Price
    previous: Price | None


@dataclass(frozen=True, slots=True)
class AlreadyStored:
    unit: Unit
    plugin_name: str
    symbol: str
    price_date: date


@dataclass(frozen=True, slots=True)
class Unpriced:
    unit: Unit
    plugin_name: str
    symbol: str
    reason: Unavailable | PriceFetchError | UnknownPricePlugin | PriceRejection


@dataclass(frozen=True, slots=True)
class Unbound:
    unit: Unit


FetchOutcome = Priced | AlreadyStored | Unpriced | Unbound


@dataclass(frozen=True, slots=True)
class FetchReport:
    outcomes: list[FetchOutcome]           # exactly one per held security
    ignored: list[UnrequestedSymbol]
```

- **A union, not one class with optional fields.** The spec's "exactly one
  outcome per held security" has four payloads, and each payload is
  meaningless on the other three: a `previous` on an unbound unit, a reason
  on a priced one. As a union those combinations cannot be built. The CLI
  `match`es with `assert_never`, and the exit code is
  `any(isinstance(o, Unpriced) for o in outcomes)`.
- **`previous` is the latest stored row before this run**, whatever its
  date. If a source ever returns a date older than the latest stored close,
  the row shows both dates honestly, and the older close is still appended:
  it is a true fact about that day, and the spec forbids only overwriting.
- **`Price` ORM rows are returned rather than copied into dataclasses.** This
  is house practice (services return `Unit`, `Account`, `JournalLine`), and
  `expire_on_commit=False` keeps their columns readable after the session
  closes.
- **`AlreadyStored` does not report whether the source now gives a different
  price for that day.** The spec defers price correction and deviation
  warnings. A source-side correction is skipped, and that is the documented
  meaning of append-only (§14.8).

### 6.8 CLI output and exit code

One `tabulate` table, one row per held security, sorted by identifier:

| column | priced | already stored | unpriced | unbound |
|---|---|---|---|---|
| `unit` | identifier | identifier | identifier | identifier |
| `source` | `plugin:symbol` | `plugin:symbol` | `plugin:symbol` | `-` |
| `outcome` | `priced` | `already stored` | `unpriced` | `unbound` |
| `date` | D | D | `-` | `-` |
| `close` | new close | `-` | `-` | `-` |
| `detail` | `previous P on D'`, or `previous none` | `-` | `str(reason)` | `-` |

- The four outcome words are fixed vocabulary, and the tests assert on them.
- **`source` shows `plugin:symbol`.** There is no `list-bindings` command in
  v1, and this table is where a user sees each unit's current binding.
- `report.ignored` prints after the table, one line each, as `str(err)`.
- **Exit code:** if any outcome is `Unpriced`, then after printing,
  `raise click.ClickException(f"{n} held securities unpriced")`. That exits
  1 with a summary line in the same `Error:` form every other command uses.
  Unbound-only and ignored-only runs exit 0, as the spec requires.
- Nothing held: `No held securities`, exit 0, and no plugin is loaded.
- `today` is `date.today()` (the user's local date), passed in by the CLI.
  Tests pass fixed dates.

---

## 7. Core validation (issue 031)

```python
def validate_close(close: Close, today: date) -> PriceRejection | None
```

This is a pure function in `prices.py`, mirroring `validate_statement` /
`validate_lines` (`-> SomeError | None`, first problem wins), and it is
testable with no database.

| Check, in this order | Rejection |
|---|---|
| `not close.price.is_finite() or close.price <= 0` | `NonPositivePrice(price)` |
| `close.price_date > today` | `FutureCloseDate(price_date, today)` |
| `close.currency != BASE_CURRENCY` | `NonBaseCurrency(currency, BASE_CURRENCY)` |

The answered-a-requested-symbol check is structural. Results are looked up
only by requested symbol (§6.6), so an unrequested result cannot reach a
unit, and a requested symbol with no result is `MissingCloseResult`.

- **`is_finite()` first is a correctness requirement, not tidiness.** It was
  verified: `Decimal("NaN") <= 0` *raises* `InvalidOperation`. Without the
  guard, one plugin returning `NaN` would raise inside the append and roll
  back every unit's close at the `BLE001` seam. `Decimal("Infinity") > 0` is
  `True`, so infinity also needs the guard. Both fold into
  `NonPositivePrice`, because neither is a strictly positive price. The
  message reads "must be a positive finite number".
- **`BASE_CURRENCY` is imported from `use_cases/journal.py`** (spec: no
  second copy). The error carries the expected currency as a field, because
  `domain_errors.py` must not import from `use_cases`.
- **Compared exactly.** `"eur"` is rejected. Normalising it would be the
  plugin's job.
- **The checks apply to every plugin, including `file`.** The file plugin
  therefore passes a zero, negative or `NaN` close through as a `Close`
  rather than rejecting it as a malformed file (§9.2). A bad value then fails
  one unit, not the whole file.

**What 030 already has and what 031 adds is split in §14.1.**

---

## 8. Freshness read (issue 032; decision 7)

```python
@dataclass(frozen=True, slots=True)
class Fresh:
    close: Price


@dataclass(frozen=True, slots=True)
class Stale:
    close: Price


@dataclass(frozen=True, slots=True)
class NoClose:
    pass


LatestClose = Fresh | Stale | NoClose


def latest_close(
    ctx: DbTransactionContext, unit_id: int, today: date, max_age_days: int = 7
) -> Result[LatestClose, PriceError]
```

- **In `use_cases/prices.py`, as a `ctx`-taking function, not a
  `UnitOfWork`.** Its only caller, portfolio reporting, will read many units
  inside its own transaction. `RecordSimpleEntry`'s docstring explains that
  one use case cannot call another, because the inner `UnitOfWork` closes the
  session. `account_balance(ctx, account_id)` is the precedent for a read
  helper that reports call per item. No CLI command and no `UnitOfWork` are
  added, because the spec gives the read function no consumer in this
  feature.
- **`unit_id`, not the identifier**, as `account_balance` takes an id. Services
  key by id, and the caller resolves names. Reporting folds `UnitBalance`,
  which today carries only `unit_identifier`. Carrying the id there is
  reporting's decision, and is recorded under Extension points.
- **N is `max_age_days`, a parameter with default 7**, not a module
  constant (spec). The default sits in the signature and nowhere else.
- **`today` is a parameter**, for the same reason as `AppendPrices`: tests
  pin the boundary day without a clock.
- **Classification:** `latest_price_service`, then:
  - no row → `NoClose()`;
  - `(today - close.price_date).days <= max_age_days` → `Fresh(close)`;
  - otherwise → `Stale(close)`.

  Age is in calendar days, so a Friday close read on Monday is 3 days old.
  With the default, age 7 is fresh and age 8 is stale, which are the
  boundary pair issue 032 asks to pin.
- **A union, not `(status, close | None)`.** The spec's "no price and stale
  price are never collapsed" becomes structural. A `NoClose` has no
  `.close` to read by mistake. `Fresh` and `Stale` always carry one, so the
  consumer reads `.close.price` without an `assert`, and mypy makes it
  handle all three.

---

## 9. The `file` plugin (issue 030)

`kohle/app/plugins/kohle_file_price_fetcher.py`, class `FilePriceFetcher`,
name `file`, entry point `file =
"kohle.app.plugins.kohle_file_price_fetcher:FilePriceFetcher"`. The module
name follows the `kohle_<source>_<kind>.py` pattern of the two importers.

### 9.1 The format

- UTF-8, comma-delimited, `.` as the decimal point, ISO `YYYY-MM-DD` dates.
  Cells are stripped and fully blank lines are skipped, which is the
  behaviour of the simple broker plugin.
- **The first line is exactly** `identifier,date,close`.
- `identifier` is the symbol bound with `set-price-source`. It is not
  necessarily `Unit.identifier` (spec).

### 9.2 Behaviour

- `KOHLE_PRICE_FILE` is read **at call time**, and an empty value counts as
  unset. Unset gives `Err(MissingEnvironmentVariable("KOHLE_PRICE_FILE"))`.
- **The whole file is parsed** before anything is returned, as the importers
  do. A malformed line anywhere is the plugin's `Err`.
- **Syntax is the plugin's job; values are core's.**
  - `Err(MalformedPriceFile(line, column, value, problem))` for:
    - a wrong header or field count;
    - an empty identifier;
    - an unparseable date;
    - a `close` that is not a decimal at all (`InvalidOperation`);
    - **a repeated `(identifier, date)`**. A hand-maintained file that
      appends a corrected line under an existing date makes "the most recent
      row" depend on line order, which is a silent wrong close. Refusing
      sends the user to edit the line instead.
  - A close that parses but is `0`, negative, `NaN` or dated in the future
    is passed through as a `Close`. Core rejects it for that unit only (§7).
- `Err(PriceFileUnreadable(path, reason))` for `OSError`,
  `UnicodeDecodeError` or `csv.Error`. These are explicit types, caught at
  the one read, as in `SimpleBrokerStatementImporter.import_statement`.
- For each requested symbol: the row with the greatest date becomes
  `Close(price_date=..., price=..., currency="EUR")`. A symbol with no rows
  becomes `Unavailable(no_symbol, f"not in {path}")`. Rows for symbols that
  were not requested are ignored.
- **`currency="EUR"` is a literal in the plugin, not `BASE_CURRENCY`.** The
  field is the plugin's claim about its data, which the spec says is EUR. If
  the ledger's base currency ever changed, an import would let the plugin
  claim the new currency for data that is still EUR. With a literal, core's
  check rejects every close loudly instead.
- **Stdlib `csv`**, as the simple broker plugin uses (`importer-plugins-for-assets.md`
  §7.4): exact `Decimal(text)`, and `line_num` for errors.

---

## 10. The `alphavantage` plugin (issue 033; decisions 3 and 4)

`kohle/app/plugins/kohle_alphavantage_price_fetcher.py`, class
`AlphaVantagePriceFetcher`, name `alphavantage`, entry point `alphavantage =
"kohle.app.plugins.kohle_alphavantage_price_fetcher:AlphaVantagePriceFetcher"`.

### 10.1 The endpoint: `TIME_SERIES_DAILY`, plus a finished-day guard

```
https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=<symbol>&apikey=<key>
```

This makes one request per symbol, built with `urllib.parse.urlencode`.

**The close stored is `"4. close"` of the latest bar in `"Time Series
(Daily)"` dated strictly before the current UTC date.**

- **Why `TIME_SERIES_DAILY`.** It is free (verified, see below), it gives the
  close **with its date**, and it is the only free equity endpoint that does
  both. `GLOBAL_QUOTE` is also free and gives `"05. price"` with `"07. latest
  trading day"`. But its finished-close field, `"08. previous close"`, has no
  date, and a holiday makes "the trading day before" unknowable without a
  calendar. `TIME_SERIES_DAILY_ADJUSTED` is premium (verified).
- **Why the guard is needed.** For `TIME_SERIES_DAILY`, the documentation
  does not say whether the latest point is a partial bar during trading
  hours. It could not be observed either: the check ran on a Sunday, and
  `"3. Last Refreshed"` is a bare date. The `GLOBAL_QUOTE` docs say "by
  default, the quote endpoint is updated at the end of each trading day for
  all users", which *suggests* free equity data is end-of-day. But the
  `FX_DAILY` / `FX_WEEKLY` docs explicitly describe "the latest data point
  ... (or partial week) containing the current trading day, updated
  realtime", so Alpha Vantage does publish partial current periods in some
  daily series. The design relies on neither reading. **The guard makes
  "never store an in-progress day" true whatever Alpha Vantage publishes.**
- **Why the UTC date, not the exchange's time zone.** The response carries
  `"5. Time Zone"`. For IBM it is `"US/Eastern"`, which was verified, so a
  per-exchange guard looked like the precise answer. But on this machine,
  **`ZoneInfo("US/Eastern")` raises `ZoneInfoNotFoundError`**, also verified.
  The system zone database has `America/New_York` but not the legacy `US/*`
  links, and no `tzdata` package is installed. The precise guard would fail
  every fetch in the user's own environment. The UTC rule needs no zone
  database. It is safe because no exchange's trading day spans midnight UTC
  on the "behind" side:
  - The Americas close by about 21:00–22:00 UTC, the same UTC date.
  - Europe and Asia trade on a local date that is the same as, or ahead of,
    the UTC date.

  So a bar still in progress always has a date ≥ the UTC date, and is
  dropped.
- **The cost is at most one day of lag.** A run after the close on day D, on
  the same UTC date, stores D−1, and the next day's run stores D. That is
  well inside the 7-day freshness threshold.
- **No `outputsize` parameter.** `compact` (the latest 100 points) is the
  documented default and the free tier. `full` is premium (verified).
  Omitting the parameter also keeps the URL identical to the documented
  example, which matters for one verified reason: the public `demo` key
  answers `function=TIME_SERIES_DAILY&symbol=IBM&apikey=demo` with data, but
  the same URL with an explicit `&outputsize=compact` gets the demo key's
  `"Information"` refusal. A manual smoke test with `demo` therefore only
  works without it.
- **The selection is a pure function**,
  `_latest_finished_close(series, before: date) -> tuple[date, Decimal] | None`,
  called with `datetime.now(UTC).date()`. Tests call it directly with
  `before` set to the fixture's newest date, and assert the in-progress bar
  is skipped. That test needs no clock seam. If no bar qualifies (a new
  listing with only today's bar), the result is `Unavailable(transient,
  "no finished daily close yet")`.
- Closes in the JSON are strings (`"227.1300"`, verified), so
  `Decimal(text)` is exact and no float ever appears.
  `currency="EUR"` is a literal, with the same reasoning as §9.2. This is the
  spec's accepted risk.

### 10.2 What was verified, and what is inferred

Checked on 2026-10-11 against the live site, with the public `demo` key and
with a fabricated key. These were design-time calls only, and the suite makes
none.

| Fact | Status | Source |
|---|---|---|
| Free tier is 25 requests/day | **verified** | support page: "25 API requests per day" |
| `TIME_SERIES_DAILY` `compact` is free; `full` is premium | **verified** | documentation page |
| `TIME_SERIES_DAILY_ADJUSTED` is premium | **verified** | documentation page |
| Response shape: `"Meta Data"` (with `"5. Time Zone": "US/Eastern"`) and `"Time Series (Daily)"` keyed by ISO date, values as strings | **verified** | live IBM response |
| Unknown symbol → HTTP **200**, `{"Error Message": "Invalid API call. ... for TIME_SERIES_DAILY."}` | **verified** | live response, status checked |
| Key refusal (demo key on a non-example URL) → HTTP **200**, `{"Information": "The **demo** API key is for demo purposes only. ..."}` | **verified** | live response, status checked |
| A fabricated key is served normally; only a *missing* `apikey` gets `{"Error Message": "the parameter apikey is invalid or missing. ..."}` | **verified** | live responses |
| Stdlib `urllib.request.urlopen`, default User-Agent, gets through the Cloudflare front with data | **verified** | live call from this venv |
| Daily quota → HTTP 200, `{"Information": "We have detected your API key as <KEY> and our standard API rate limit is 25 requests per day. ..."}`. **The key is echoed in plain text** | inferred | several independent third-party bug reports and PRs (2025–2026); not reproducible without burning a real key's quota |
| Burst limit of 1 request/second → HTTP 200, `{"Information": "... spreading out your free API requests more sparingly (1 request per second) ..."}` | inferred | the same kind of third-party reports; **not in the official documentation** |
| Whether `TIME_SERIES_DAILY` shows today's partial bar during trading hours | **unknown** | undocumented and unobservable on a weekend. The guard makes it irrelevant (§10.1) |
| `alpha_vantage` 3.0.0 (PyPI) raises the same `ValueError` for `"Error Message"` and `"Information"` / `"Note"`, and depends on `requests` and `aiohttp` | **verified** | the package's source, `alphavantage.py` lines 358–363 |

### 10.3 Recognising throttling, and the per-response rule

Throttling arrives **in the body, with HTTP 200**, as shown in the table. Each
response body is classified by **which top-level key is present, never by
message text**:

| Body has | Meaning | Result |
|---|---|---|
| `"Time Series (Daily)"` | data | `Close`, or `Unavailable(transient)` if no finished bar (§10.1) |
| `"Error Message"` | the provider rejects this request; for a well-formed request with a key, the symbol is not carried | `Unavailable(not_covered, <message>)` |
| `"Information"` | the provider refuses to serve this key right now: daily quota, burst limit, or a premium-only notice | `Unavailable(transient, <message>)` **for this symbol and every one after it, and no further requests** |
| none of these, or not a JSON object | the provider's format is not what this plugin understands | `Err(UnexpectedAlphaVantageResponse(symbol, problem))` |

- **The rule is by key, not by text, deliberately.** The burst notice also
  mentions the 25-per-day quota (third-party reports), so text matching
  cannot reliably tell the two apart, and both mean the same thing here:
  stop, keep what you have, try later. A premium-only notice also lands as
  `transient`, with the provider's text as `detail`. That is why the detail
  exists (§2.2).
- **This is the spec's throttle behaviour.** Closes fetched before the notice
  are kept, every symbol not reached is `transient`, and the result is
  `Ok`, so those closes are written and the run exits non-zero because units
  ended unpriced.
- **The plugin never reorders.** It requests in exactly the order received,
  and the symbols after a throttled one are exactly those it did not reach.
  That is contract rule 6 (§2.3), and it is what lets core's oldest-first
  order (§6.4) spend the daily quota on the stalest symbols. Sorting or
  deduplicating inside the plugin would silently undo the rotation.
- **Only `"Information"` is recognised.** `"Note"` was the throttle key in
  older API versions, and the `alpha_vantage` library still checks it. It was
  not observed, and recognising it would be handling a case not shown to
  exist. If it reappears, the body falls into the last row and the plugin
  fails loudly.
- **`"Error Message"` is not mapped to a key error.** The only key error
  observed is for a *missing* `apikey`, and the plugin never sends a request
  without one. A fabricated key was served. If some key were ever refused
  this way, every symbol would show `not_covered:` followed by Alpha
  Vantage's own sentence about the key, which explains itself.
- **Transport failures are a whole-plugin `Err`.** These are `OSError`,
  which covers `URLError`, `HTTPError` for non-2xx and `TimeoutError`, all
  verified to be `OSError` subclasses. The result is
  `Err(AlphaVantageUnreachable(...))`, even mid-run. The spec makes offline
  a plugin `Err`, and a drop mid-run is being offline. The alternative is in
  §12, Alternatives rejected.
- **A non-JSON body** (`ValueError` from `json.loads`, for example a
  Cloudflare HTML page) and an unparseable close or date
  (`InvalidOperation` / `ValueError`) give
  `Err(UnexpectedAlphaVantageResponse(...))`. When the format is
  misunderstood, the closes parsed earlier in the run are not trusted
  either.

### 10.4 Key handling and redaction

- `KOHLE_ALPHAVANTAGE_KEY` is read at call time, and an empty value counts as
  unset. Unset gives `Err(MissingEnvironmentVariable(...))` **before any
  request**, and the tests assert `http_get` is never called.
- **Every provider text the plugin passes on has the key replaced by `***`.**
  That covers `Unavailable.detail` and every error message. This is forced by
  the inferred daily-quota notice, which echoes the key verbatim (§10.2). An
  unredacted detail would put the key in terminal scrollback and in any
  output a user pastes into an issue. The request URL carries the key too,
  so no message is ever built from the URL. `urllib`'s `URLError` /
  `HTTPError` strings do not include it, and redaction covers them anyway.

### 10.5 HTTP client and the test seam (decision 3)

**Stdlib `urllib.request`. No dependency is added.**

```python
class AlphaVantagePriceFetcher(PriceFetcherPlugin):
    def __init__(
        self,
        http_get: Callable[[str], bytes] = _urlopen_get,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None: ...
```

`_urlopen_get(url)` is `urlopen(url, timeout=30)` followed by `.read()`. It
raises `OSError` on any transport failure or non-2xx status.

- **The seam is constructor injection with production defaults.**
  `load_price_plugins` instantiates with no arguments and gets the real
  network. Tests build `AlphaVantagePriceFetcher(http_get=fake, sleep=...)`
  and hand it to the CLI through the monkeypatched `load_price_plugins`,
  exactly as the importer CLI tests hand over a fake importer. The fake
  receives the full URL. It can therefore assert `function=TIME_SERIES_DAILY`
  and the absence of `outputsize`, and it dispatches fixture bodies by the
  `symbol` query parameter, or raises `URLError` to simulate being offline.
- **Pacing: one second between consecutive requests**, never before the
  first. The burst limit is inferred, not documented (§10.2). But being
  wrong in the other direction is expensive: unpaced, every run would get one
  close, then a burst notice, then all the rest `transient`, and might burn
  quota for nothing. 25 symbols cost about 25 seconds. `sleep` is injected
  only so the suite does not spend real seconds. A recording fake also lets
  a test assert the pacing.
- **No clock seam.** The finished-day rule is tested on the pure selector
  (§10.1). End-to-end fixtures are recorded and so are always in the past.

### 10.6 Fixtures

`tests/fixtures/alphavantage/`:

| File | Content |
|---|---|
| `daily.json` | the recorded IBM `TIME_SERIES_DAILY` body, trimmed to its `Meta Data` and three bars |
| `unknown_symbol.json` | the recorded `{"Error Message": ...}` body |
| `demo_key_refused.json` | the recorded demo-key `{"Information": ...}` body, a real throttle-class refusal |
| `daily_limit.json` | the daily-quota body as third-party reports quote it, **with the key `TESTKEY`**, so the redaction test asserts `TESTKEY` never reaches output. **Reconstructed, not recorded**: capturing it needs a real key's exhausted quota, and the test that loads it says so |

The throttle scenario uses two units bound to symbols `A` and `B`. The fake
answers `A` with `daily.json` and `B` with `daily_limit.json`. That is issue
033's "throttled after the first symbol": `A` is written, `B` is `transient`,
and the run exits 1. Neither has a stored close, so the tie breaks by symbol
and `A` goes first.

The ordering scenario binds `A` and `B` again, but `A` already has a stored
close from an earlier run and `B` has none. Core asks for `B` first.
Throttled after the first request, `B` is written and `A` is `transient`.
That is issue 033's oldest-first criterion end to end, and the opposite of
what alphabetical order would do.

---

## 11. The structural guard tests (issue 034)

Three tests, matching the issue's three criteria.

1. **No reference from recording or import code.**
   - A static AST walk over `kohle/use_cases/journal.py`,
     `kohle/use_cases/classification.py`, `kohle/use_cases/splitting.py`,
     `kohle/plugin/importer_plugin.py` and the source of
     `cli.import_statement`'s callback (`inspect.getsource`). It collects
     every imported module and name, and every `Name` / `Attribute`
     identifier, and asserts none is in `{Price, PriceBinding,
     PriceFetcherPlugin, load_price_plugins}` and no import is from
     `kohle.plugin.price_plugin`, `kohle.services.price_services` or
     `kohle.use_cases.prices`. **Exact identifiers, not substrings**:
     `unit_price` and `--from-price` are recording vocabulary, not
     references to the price table.
   - A subprocess imports the three use-case modules and asserts the three
     price modules are absent from `sys.modules`. That catches a transitive
     reference the AST walk cannot see.
2. **No price plugins, no change in output.** A scripted run of existing
   commands (`add-account`, `add-unit`, `record` with `--to-unit`,
   `import-statement` with the simple broker fixture, `balance`, `net-worth`,
   `list-operations`, `list-importer-plugins`) through `CliRunner`, twice,
   each on a fresh `session_factory`. One run has
   `kohle.plugin.plugin_manager.entry_points` returning the installed set;
   the other has it with the price entry points filtered out. The two
   outputs must be identical. The existing CLI tests, which keep passing
   unchanged, are the "same as before the feature" half.
3. **A third plugin, without touching core.** A `PriceFetcherPlugin`
   subclass is defined in the test module. `plugin_manager.entry_points` is
   patched to return the installed entry points plus
   `importlib.metadata.EntryPoint(name="third",
   value="tests.<module>:<Class>", group="kohle.plugins")`. Constructing
   and loading such an `EntryPoint` was verified in this venv. Then
   `set-price-source X third SYM` and `fetch-prices` are run and the close is
   asserted stored. This goes through the real discovery and partitioning
   path, not a monkeypatched loader. The "without changing core" half holds
   by construction, because the test edits nothing else.

As with the importer design, any test that asserts the *installed* `file` /
`alphavantage` entry points needs `uv sync` after `pyproject.toml` changes.
A failure there means "reinstall", not a bug.

---

## 12. The decision categories

### State and data lifecycle

- **`set-price-source`:** one row created, updated, or left unchanged, in one
  transaction, with one audit `Operation` when it writes (§5.3).
  - *Reversible* by rebinding.
  - *Not auditable in content*: the update `Operation` does not record the
    previous plugin and symbol, which is the house limitation.
  - An unchanged rebind leaves no trace.
- **`fetch-prices`:** three phases, and only the third writes.
  - **The unit of success is one held security's close**, not the run (spec:
    price rows are independent facts). The transaction boundary is still the
    whole append. That is correct because every per-unit failure is decided
    as a value before any write, and only a database failure or a bug can
    fail the transaction (§6.6).
  - **Not atomic across phases, deliberately.** Plugin calls happen between
    two transactions. If the append then fails, for example because the
    database is locked, the fetched closes are lost and Alpha Vantage quota
    has been spent. The user re-runs. That is the price of keeping network
    I/O out of transactions, which the spec requires.
  - **Between the phases, the ledger can change** (a concurrent rebind or
    sale). A close may then be appended for a unit that is no longer bound or
    held. That is harmless, because a close is a true fact about the unit
    either way.
  - **Replayable and idempotent:** a re-run over unchanged sources writes
    nothing, reports `already stored` for every unit and leaves no
    `OperationGroup`.
  - **Append-only by absence.** For `Price`, `price_services` defines `add`,
    `exists` and `latest`, and no update or delete exists to call. "No code path updates
    or deletes a price row" is a property of the module's contents.
  - **Auditable:** each new close is one `create prices <id>` `Operation`,
    grouped per run.
  - **The request order is derived, never stored.** The price table is the
    rotation state for oldest-first ordering (§6.4), so nothing extra has to
    stay consistent with it.
- **Migrations:** the binding table's downgrade refuses on data. The
  uniqueness change round-trips losslessly (§4).

### Error propagation

Five representations, and where they change:

1. **Plugin.** `PriceFetchError` subclasses, each with `__str__`, for
   whole-plugin failure:
   - contract: `MissingEnvironmentVariable`;
   - file: `PriceFileUnreadable`, `MalformedPriceFile`;
   - Alpha Vantage: `AlphaVantageUnreachable`, `UnexpectedAlphaVantageResponse`.

   Per-symbol problems are `Unavailable` values. Explicit catches happen at
   the one place each failure arises (§9.2, §10.3). **A plugin bug is not
   caught.** `call_price_plugins` does not wrap plugin calls in a broad
   `except`, for the reason the importer design gives: it would add a third
   `BLE001` site beyond the two `AGENTS.md` sanctions, and it would hide the
   bug. The consequence is recorded in §14.9: a raising plugin aborts the run
   before the append, so no other plugin's rows are written either.
2. **`call_price_plugins`.** Plugin results pass through unchanged. An
   uninstalled plugin becomes `UnknownPricePlugin`, in the same slot as a
   plugin's own `Err`.
3. **`AppendPrices`.** Every plugin `Err`, `Unavailable`, `UnknownPricePlugin`
   and `PriceRejection` **stops being an error at this seam** and becomes
   `Unpriced.reason`, a value inside `Ok(FetchReport)`. Only `PriceError`
   from a service (the database) is the use case's `Err`. That conversion is
   what per-unit isolation means in code.
4. **Other use cases.**
   - `SetPriceSource`: `UnitError` (`UnitNotFoundError`, `NotASecurityUnit`)
     or `PriceError` (`UnknownPricePlugin`, `EmptyPriceSymbol`, infrastructure).
   - `ListPriceTargets`: `BalanceError` (from `held_units`) or `PriceError`.
   - `latest_close`: `PriceError`.
5. **CLI.** It never inspects an error type, and prints `str()` of every
   error and every `Unavailable`. `fetch-prices` exits 1 through
   `ClickException` when anything is unpriced (§6.8).

```
PriceError(Exception)                       services' infrastructure failures, and:
  UnknownPricePlugin(name, available)
  EmptyPriceSymbol()
MissingCloseResult(symbol)                  per-unit rejections, Exception subclasses as values
NonPositivePrice(price)
FutureCloseDate(price_date, today)
NonBaseCurrency(currency, base)
UnrequestedSymbol(plugin_name, symbol)      reported in FetchReport.ignored, never per unit

PriceRejection        = MissingCloseResult | NonPositivePrice | FutureCloseDate | NonBaseCurrency
SetPriceSourceError   = UnitError | PriceError
ListPriceTargetsError = BalanceError | PriceError
```

- **The rejections are not `PriceError` subclasses.** If they were,
  `AppendPrices`'s `Err` type would include them, and the type would stop
  saying "an `Err` here means the database failed". This follows the
  `StatementError` precedent of an alias over plain `Exception` subclasses.
- **No named error for the `prices` unique violation.** It is reachable only
  by a concurrent run (§6.6), and SQLite's message, wrapped in `PriceError`,
  is already readable.
- **`NotASecurityUnit.__str__` loses "and cannot be a traded instrument".**
  `set-price-source` reuses the error (spec), and that clause describes
  importing. The new message is `Unit 'EUR' is a currency, not a security`.
  The only test of the error asserts `isinstance`, not the text, which was
  checked.
- **`plugin_manager` still raises** `TypeError` for a neither-kind class and
  `ValueError` for a duplicate name. Both are pre-existing, and both are
  installation errors that should stop every plugin-using command before it
  does anything. They are not runtime conditions to report as values.

### Concurrency and ownership

**Single-threaded, with no shared mutable state.** Plugins are called one
after another. The Alpha Vantage plugin pauses one second between requests
and never in parallel.

- **Plugin instances hold no state between calls** (contract rule 5).
  `load_price_plugins` builds fresh instances per command, which would hide a
  violation. A future TUI holding one instance would expose it, so the
  contract states the rule.
- **The plugin-to-core hand-off is immutable.** `Close` and `Unavailable`
  are frozen. `PriceTargets` and the outcome types are frozen dataclasses.
  The dicts inside them are built once, by one function, and only read
  afterwards.
- **Sessions:** two, created by the CLI, each owned and closed by its
  `DbTransaction`. No session is open during a plugin call.
- **Two concurrent `fetch-prices` runs:** SQLite's single writer serialises
  the appends. A loser that raced past the existence check hits
  `uq_price_unit_date`, rolls back whole, writes nothing and exits non-zero.
  Its re-run reports `already stored`. Two runs also spend Alpha Vantage
  quota twice. Neither case is guarded, because this is a single-user CLI.

### Reuse

Used rather than reimplemented:

- **`aggregate_by_unit`, `account_lines_service`, `list_accounts_service`**:
  the held-units fold (§6.2), which the spec names.
- **`get_unit_by_identifier_service`, `UnitNotFoundError`, `NotASecurityUnit`**:
  binding refusals (spec).
- **`BASE_CURRENCY`**: the currency check (spec).
- **The insert-or-update shape of `set_split_adjusting_entry_service`**:
  binding upsert.
- **Check-then-insert, as in `existing_references_service`**: idempotent
  price append.
- **`crud_create` / `crud_update` and the lazy `OperationGroup`**: the audit
  trail, and invisible replays.
- **The importer contract's conventions**: a leaf module, frozen / slotted /
  `kw_only` types, named `__str__` errors, plugin errors in the plugin
  module.
- **Stdlib `csv` and the simple broker's strictness**: the file plugin.
- **`entry_points(group="kohle.plugins")`**: the same discovery, now
  partitioned.

Introduced here and worth reusing next:

- **`held_units(ctx)`**: portfolio reporting's definition of a position.
- **`latest_close(ctx, ...)`**: reporting's only price read.
- **`latest_price_service`**: one read serves the `previous` close, the
  freshness classifier and the request order.
- **`oldest_close_first`**: fair use of a quota for any limited plugin, with
  no plugin-specific code.
- **`_load(kind)`**: a third plugin kind is one more ABC in its
  neither-kind check plus a one-line `load_*` function.
- **`MissingEnvironmentVariable`**: any plugin configured from the
  environment.
- **The key-presence response classifier and key redaction**: the next
  HTTP-backed price source, if it reports errors the same way.

### Extension points

- **The `PriceFetcherPlugin` contract** is the public seam (spec: core is
  plugin-agnostic, held by §11's third-plugin test). Its stability rests on:
  - the method signature;
  - the `Close` / `Unavailable` field sets;
  - the rule that results are keyed by requested symbol.

  Adding a field *with a default* to `Close` is compatible. Adding an
  `UnavailableReason` value is compatible with core, which treats every
  reason alike, but a plugin cannot use it before core knows it. There is no
  version negotiation, as with importers.
- **A plugin's `name` is persisted** in `price_bindings.plugin_name` and
  `prices.source`. Renaming a plugin orphans its bindings, and they then
  report `UnknownPricePlugin` at fetch time. That is a contract obligation on
  plugin authors, recorded here.
- **Portfolio reporting** consumes `latest_close` and `held_units`.
  `UnitBalance` carries only the identifier, so reporting will need the unit
  id alongside it. That is its decision to make.
- **Request order is part of the contract** (rule 6, §2.3). A future plugin
  with a quota gets the oldest-first rotation (§6.4) just by spending its
  requests in the order given. A different policy, for example weighting by
  position size, would replace `oldest_close_first` and nothing else.
- **Commodities** (a Non-Goal) need two relaxations: the kind filter in
  `ListPriceTargets` and the kind check in `SetPriceSource`. Nothing else
  knows about kinds.
- **FX** (a Non-Goal): `Close.currency` already exists, so a conversion step
  would sit beside `validate_close`. Nothing is built.
- **No `list-bindings`, `unbind`, `list-price-plugins` or manual-entry
  command.** `fetch-prices` shows each binding in its `source` column, and
  `set-price-source`'s refusal lists the plugins. The spec asks for no more.

### Build vs. buy

- **HTTP: stdlib `urllib.request`.**
  - *`requests`* and *`httpx`* are not dependencies today. Each would add a
    transitive set (`urllib3`, `certifi`, `idna`, `charset-normalizer`, or
    `httpcore`, `anyio` and others) for one GET with a query string. Nothing
    either offers is used: no sessions, auth, retries, streaming or async.
  - Stdlib was verified to reach Alpha Vantage through Cloudflare with its
    default User-Agent (§10.2).
- **Alpha Vantage client: build.**
  - *`alpha_vantage` 3.0.0* (PyPI) was evaluated from its source. It depends
    on `requests` and `aiohttp`, and it raises one `ValueError` for both
    `"Error Message"` and `"Information"` / `"Note"`. Those are exactly the
    two cases this plugin must tell apart (`not_covered` versus throttled).
    Using it would mean parsing exception text to undo the information it
    discarded.
- **Test HTTP layer: constructor injection.**
  - *`responses`* and *`pytest-httpserver`* add dev dependencies to replace
    one callable.
  - *`vcrpy`* records real traffic, and Alpha Vantage's query string *is* the
    API key, so cassettes would need scrubbing. It would also re-record
    whatever the provider says today, rather than the curated cases
    (throttled mid-run, unknown symbol) the tests need.
  - *Monkeypatching `urllib.request.urlopen`* patches a global, and couples
    every test to the implementation's choice of call.
- **Time zones: none, by design.**
  - *`zoneinfo`* cannot resolve the `"US/Eastern"` Alpha Vantage returns on
    this machine (verified).
  - *The `tzdata` package* would fix that, but adds a dependency for a guard
    the UTC rule provides without one (§10.1).
- **CSV: stdlib `csv`** (§9.2).
- **Idempotent insert: house check-then-insert**, over SQLite's `INSERT ...
  ON CONFLICT DO NOTHING`. `crud_create` needs an ORM entity with an `id` to
  audit, and a conflict-skip yields none, so the audit decorator would have
  to learn a "nothing inserted" case. The existence check is also what
  produces the `already stored` outcome the spec wants reported.
- **Binding upsert: the house read-then-write**, over `ON CONFLICT DO
  UPDATE`, for the same audit reason, and to get the no-write path for an
  unchanged rebind.

### Abstractions introduced

| Abstraction | Forcing problem |
|---|---|
| `PriceFetcherPlugin`, `Close`, `Unavailable`, `UnavailableReason`, `PriceResult` | The spec: a second plugin kind with typed per-symbol results and no DataFrames. |
| `Unavailable.detail` | Alpha Vantage's three `"Information"` cases share one reason, and a premium-only endpoint would otherwise be indistinguishable from throttling, for ever (§2.2). |
| `PriceFetchError`, `MissingEnvironmentVariable` | Whole-plugin failure as a value (spec); both bundled plugins need the missing-variable error. |
| `_load(kind)` + `load_price_plugins` | Partition by kind while leaving `load_plugins`'s callers and their monkeypatches untouched (§3). |
| `PriceBinding` model and table | The spec. |
| `price_services` functions | Only services touch a `Session` (`AGENTS.md`). |
| `held_units(ctx)` | The spec defines held as `aggregate_by_unit` across all accounts. A SQL sum would be a second, float-inexact definition (§6.2). |
| `PriceTargets` | The hand-off from the first transaction, through the plugins, into the second. It is the grouping the spec describes. |
| `oldest_close_first` (pure) | Issue 033: with more symbols than a run's quota, a fixed order starves the same tail every day. Pure, so its shared-binding rule and tie-break are tested directly (§6.4). |
| `PriceTargets.request_order` | The order is a quota-spending policy. Carried by dict insertion order, it would be undone by any re-sort (§6.4). |
| `call_price_plugins` | One call per plugin, and an uninstalled plugin becomes a per-unit reason, the same from any frontend (§6.5). |
| `Priced` / `AlreadyStored` / `Unpriced` / `Unbound`, `FetchReport` | Exactly one outcome per held security, with four incompatible payloads. The exit code is a function of the outcome type (§6.7). |
| `validate_close` (pure) | The spec's uniform core checks, testable without a database, like `validate_statement`. |
| `Fresh` / `Stale` / `NoClose`, `latest_close` | The spec's three-way classification, with "none" and "stale" not collapsible (§8). |
| `PriceError` family, rejections, `UnrequestedSymbol` | Named reasons the spec requires, each with `__str__`, because the CLI prints `str()`. |
| `FilePriceFetcher`, `AlphaVantagePriceFetcher` and their errors | Issues 030 and 033. |
| `http_get`, `sleep` constructor seams | No live network in the suite (spec), and no real one-second pauses in it. |
| `_latest_finished_close` (pure) | The never-store-today rule is tested directly, so no clock seam is needed. |

Explicitly **not** introduced:

- **A shared plugin base class** for `name`. That is two abstract one-liners,
  and the manager must know both kinds anyway.
- **A rate-limiter or retry class.** It is one `sleep` call, and the spec
  says throttling means "report transient and stop", not retry.
- **A clock abstraction.** `today` is a parameter where core needs it, and
  the plugin's guard is a pure function.
- **A symbol-uniqueness check across units** (§14.6), and **a currency
  column** (spec).
- **A pre-check in the uniqueness migration** (§4.3).
- **A `UnitOfWork` around `latest_close`.** It has no caller in this feature.
- **A persisted rotation cursor.** The price table already is one (§6.4).

### Alternatives rejected

| Rejected | Where | Short reason |
|---|---|---|
| Insert, then catch the unique violation | §6.6 | verified: the first violation poisons the session, and every later write in the run fails |
| A `SAVEPOINT` per unit | §6.6, State | pysqlite needs the isolation-level workaround `connection.py` does not apply; `DbTransactionContext`'s `transaction_steps` list and lazily flushed `OperationGroup` are not savepoint-aware, so a rolled-back unit would leave its `Operation` queued or roll back the group row itself |
| One `UnitOfWork` per unit | §6.6 | N `OperationGroup`s and N sessions per run, against the spec's one append; it isolates only database failures, which fail every unit alike |
| A SQL `SUM ... HAVING != 0` for held units | §6.2 | verified: SQLite stores the quantities as `REAL`, so a sold-out fractional position sums to 2.78e-17 and stays "held" |
| `load_plugins(kind)` with a parameter, or `load_plugins()` returning both kinds | §3.2 | changes every existing call site and the importer tests' monkeypatches |
| A second entry-point group | §3.1 | the spec keeps one group |
| Kind declared by metadata or naming convention | §3.1 | the ABC already declares it |
| Skipping neither-kind entry points silently | §3.2 | a broken registration would vanish instead of failing |
| A list result aligned with `symbols` | §2.2 | an off-by-one silently gives one unit another unit's close |
| Reason-only `Unavailable` (the spec's literal shape) | §2.2 | premium-only and throttled become indistinguishable |
| `UnavailableReason` as `Literal` strings | §2.2 | house enums are `Enum` |
| `GLOBAL_QUOTE` for the close | §10.1 | its finished close (`previous close`) has no date |
| Trusting `TIME_SERIES_DAILY`'s latest bar | §10.1 | intraday behaviour is undocumented, and Alpha Vantage FX daily series do publish partial periods |
| An exchange-time-zone guard from `"5. Time Zone"` | §10.1 | verified: `"US/Eastern"` does not resolve on this machine |
| A local-date guard | §10.1 | correct only for users not far east of the exchange; the UTC rule is location-independent |
| `outputsize=compact` in the URL | §10.1 | it is the default already, and it breaks the `demo` key smoke test (verified) |
| Matching throttle messages by text | §10.3 | the burst notice also mentions the daily quota; keys are stable where wording is not |
| Recognising the legacy `"Note"` key | §10.3 | not observed; an unrecognised body already fails loudly |
| Keeping closes on a mid-run transport failure | §10.3 | the spec makes offline a whole-plugin `Err`; a drop during a run of a few seconds is rare, and the common case, throttling, already keeps closes |
| Passing the provider's text through unredacted | §10.4 | the daily-quota notice echoes the key |
| No pacing between requests | §10.5 | an unpaced run may get one close a day |
| `requests` / `httpx` / `alpha_vantage` | Build vs. buy | dependencies for one GET; `alpha_vantage` merges the two cases the plugin must separate |
| `vcrpy` / `responses` / patching `urlopen` | Build vs. buy | dependency, key-bearing cassettes, or a global patch |
| `INSERT ... ON CONFLICT` for prices or bindings | Build vs. buy | the audit decorator needs an entity; `already stored` must be reported |
| One migration for both schema changes | §4.1 | ships 030's constraint early, and the model and the database disagree for a slice |
| Refusing the uniqueness downgrade on data | §4.3 | the downgrade is lossless |
| Archivable `PriceBinding` | §4.2 | `deleted_at` would have no legitimate non-null value |
| Unbind-then-insert history for bindings | §5.3 | the spec asks for replacement; it would also need a partial unique index |
| The plugin check in the CLI | §5.2 | splits the refusals across two layers; untestable without `CliRunner` |
| `BASE_CURRENCY` in plugins | §9.2 | the plugin's currency is a claim about its data, not about the ledger |
| Rejecting zero, negative or `NaN` closes in the file plugin | §9.2 | turns one bad cell into a whole-file failure; core owns value checks |
| Last line wins for a repeated `(identifier, date)` | §9.1 | a silent, order-dependent close |
| `latest_close` as a `UnitOfWork` | §8 | reporting must call it inside its own transaction |
| `(status, close \| None)` for freshness | §8 | lets "fresh with no close" be built, and forces `assert`s on the consumer |
| Plugin calls inline in the CLI | §6.1 | the not-installed reason would live only in one frontend |
| Alphabetical (`sorted`) request order | §6.4 | with more symbols than the quota, the same tail is unpriced every day, for ever |
| Ordering inside the plugin | §6.4 | a plugin cannot read stored closes, and every limited plugin would need its own copy |
| Ordering only for `alphavantage` | §6.4 | core would special-case a plugin name, against the spec's plugin-agnosticism |
| A persisted round-robin cursor | §6.4 | a second record of what the price table says, which can disagree after a failed append |
| A random shuffle per run | §6.4 | bounded only in expectation, and untestable without a seed |
| A shared symbol ranked by its *newest* unit | §6.4 | a newly added unit would wait behind every symbol priced since |
| Order carried by dict insertion order | §6.4 | invisible; one display `sorted()` silently restores the starvation |
| Tie-break by unit identifier | §6.4 | ambiguous when two units share a symbol |
| A broad `except` around plugin calls | Error propagation | a third `BLE001` site, and it hides plugin bugs |

---

## 13. Issue mapping

| Issue | Lands |
|---|---|
| 029 bind | `price_plugin.py` (whole contract); `plugin_manager` partition + `f`-string fix; `PriceBinding` + migration 1; `PriceError`, `UnknownPricePlugin`, `EmptyPriceSymbol`, `SetPriceSourceError`; `NotASecurityUnit` wording; `price_bindings_service`, `set_price_binding_service`; `SetPriceSource`; `set-price-source`; tests with a test-local fake plugin; README command |
| 030 fetch via file | migration 2, off 029's revision, + `Price` model change; `held_units`; `ListPriceTargets`, `PriceTargets` (without `request_order`), `ListPriceTargetsError`; `call_price_plugins`, passing `sorted(symbols)` until 033; `AppendPrices` with the four outcomes, `FetchReport`, `MissingCloseResult`, plugin-`Err` isolation and the non-zero exit for `Unpriced` (§14.1, now in the issue); `add_price_service`, `price_exists_service`, `latest_price_service`; `FilePriceFetcher` + entry point; `fetch-prices` |
| 031 validate and isolate | `validate_close` and `NonPositivePrice`, `FutureCloseDate`, `NonBaseCurrency`, `PriceRejection`; `UnrequestedSymbol` reporting in `FetchReport.ignored` (§14.3, now in the issue); the isolation tests, including a pair of units on one binding (§14.2) |
| 032 freshness | `Fresh` / `Stale` / `NoClose`, `latest_close`; boundary tests |
| 033 Alpha Vantage | `AlphaVantagePriceFetcher` with its errors, seams, selector and redaction; entry point; `tests/fixtures/alphavantage/`; **request order**: `oldest_close_first`, `PriceTargets.request_order` filled by `ListPriceTargets` from `latest_price_service`, `call_price_plugins` switched from `sorted` to it, contract rule 6 added to the docstring (§6.4); README section |
| 034 guards | the three tests in §11 |

**Dependency order is 029 → 030 → {031, 032, 034} → 033**, as the issues
declare. 032 and 034 need only 030.

**033 is no longer plugin-only.** Its ordering criterion changes
`ListPriceTargets`, `PriceTargets` and `call_price_plugins` in core. The
change names no plugin, so §11's third-plugin test still holds after it, and
the test needs no change if 034 lands first.

After 033 lands, `AGENTS.md`'s Context should mention that plugins come in
two kinds from one entry-point group, and that `fetch-prices` is the only
writer of `prices`. That edit belongs to the post-landing update.

---

## 14. What the spec and the issues got wrong, or left open

Recorded because the design deviates from them or settles them, and a later
reader needs to know that was deliberate.

1. **Issue 030 could not be finished without part of 031.** *Adopted:
   issue 030 was edited to match.* 030 ships the file
   plugin, which returns `Unavailable(no_symbol)` and, when
   `KOHLE_PRICE_FILE` is unset, an `Err`. But 030's acceptance criteria list
   only `priced`, `already stored` and `unbound`, and give `unpriced` and the
   non-zero exit to 031. Exiting 0 with nothing written because the file
   variable is unset would be a half-finished slice. **The `Unpriced` outcome
   and the exit code land in 030**, for the reasons 030's own plugin can
   produce: `Unavailable`, plugin `Err`, uninstalled plugin, missing result.
   031 keeps the three value checks, the unrequested-symbol report and the
   isolation tests.
2. **Issue 031's isolation tests need a second plugin in the same run.** The
   file plugin is the only real one by then, so they use a test-local fake
   beside it. This is noted so it is not read as skipping the real plugin.

   **031's edited criterion, "including two units that share one plugin and
   symbol", describes a split that cannot happen.** Validation runs on the
   close, and both units receive the same close, so a shared pair always
   gets the same verdict. What the test can pin, and does (§15), is twofold.
   A rejected shared close leaves both units unpriced while a third unit's
   valid close is written in the same run. And with a valid shared close,
   the per-unit existence check can still differ: one unit `already stored`
   and the other `priced`, without either affecting the other.
3. **"A result for a symbol that was not requested" cannot be a per-unit
   rejection.** *Adopted: issue 031 was edited to match.* The spec lists it among checks where "a violation makes that
   unit unpriced", and issue 031 says it "leaves the table unchanged for that
   unit". An unrequested symbol has no unit. If it happens to be bound to a
   unit under *another* plugin, that unit's outcome belongs to the other
   plugin. The design keeps the intent: the result can never reach the
   table, because lookup is by requested symbol only. It reports
   `UnrequestedSymbol` on its own line after the table, and **does not
   affect the exit code**, because the spec ties the exit code to bound
   units ending unpriced.
4. **The uniqueness migration is not "off the current head
   (`a1cebfe54f33`)".** *Adopted: issue 030 now says "off 029's revision".* With one migration per slice (§4.1), it is off 029's
   binding migration. The spec allowed the binding table "in the same
   migration or one beside it", and this is the beside-it reading.
5. **Plugin calls sit in `use_cases/prices.py::call_price_plugins`, called
   from the CLI, not inline in the CLI** as `import_statement` does. The
   precedent's substance holds: no plugin runs inside a transaction, and the
   append use case receives the results (§6.1).
6. **The spec is silent on two units bound to the same `(plugin, symbol)`.**
   The design allows it: the symbol is requested once and the close is
   applied to every unit bound to it (§6.3). Refusing it would be a rule the
   spec does not state.
7. **`Unavailable` gains `detail: str`**, beyond the spec's "carries the
   reason". The spec settles the shape at design time, and the forcing case
   is in §2.2.
8. **`already stored` hides a changed source value.** If a source revises a
   close for a day already stored, the run reports `already stored` and does
   not say the value differs. That is a direct consequence of the spec's
   append-only and no-correction Non-Goals, and is recorded so it is not
   mistaken for a bug.
9. **A plugin bug aborts the whole run.** "Rows from the other plugins in the
   same run are still written" holds for a plugin's `Err`, which is the
   spec's case. A plugin that *raises* propagates out of
   `call_price_plugins` before the append opens, so nothing is written. That
   is the importer design's position on plugin bugs, applied consistently.
10. **Oldest-close-first request order comes from issue 033, not from the
    frozen spec.** The spec calls mid-run throttling "the normal case" but
    does not say which symbols go first. The first pass of this design kept
    the order alphabetical and recorded the consequence: with more symbols
    than the daily quota, the same tail starves every day. The user put the
    fix in scope through 033's edited criteria. It is built in §6.4, with the
    plugin's obligation in §2.3 rule 6. It is recorded here because a reader
    of the spec alone would not expect it.
11. **"Held across all accounts" equals "held in asset accounts" only while a
    security never appears on an income, expense or equity line.** Every
    recording path today posts a trade as security against EUR, so they
    coincide. A `record-split` that puts a security on both sides of a
    non-transfer entry would hide the position. The spec defines held this
    way, and the design follows it.
12. **The Alpha Vantage API key leaks through the daily-quota notice**, by
    third-party report. The spec does not mention it, and the design adds
    redaction (§10.4).
13. **`NotASecurityUnit`'s message is import-specific.** Reused for
    `set-price-source` as the spec requires, its wording is generalised
    (Error propagation).

**Incidental, out of scope:** `tests/test_migration_downgrade.py` carries
`BEFORE_SPLITS = "TODO"` and `BEFORE_SPLIT_GROUPS = "TODO"`. They are unused,
and the splitting migrations have no round-trip tests. That is a one-line
cleanup for a `change`, not this feature.

---

## 15. Testing notes

This extends the existing layers: pure functions with no fixture, services
and use cases against `session` / `session_factory`, the CLI through
`CliRunner`, and migrations through Alembic against a file database.

**Pure, no database:**

- `validate_close`: zero, negative, `NaN`, `Infinity`, the day after
  `today`, `today` itself (accepted), `"USD"`, `"eur"`, and a clean close
  (`None`). Each rejection has its own type.
- `oldest_close_first`:
  - a symbol with no stored close comes before every dated one;
  - dated symbols come oldest first;
  - equal dates break by symbol;
  - a symbol shared by two units ranks by the older of their dates, and a
    `None` on either unit puts it first;
  - an empty mapping gives an empty list;
  - **a simulated rotation**: 30 symbols, a quota of 25, each "run" taking
    the first 25 of the function's output and stamping them with that run's
    date. Every symbol is refreshed at least once in every 2 consecutive
    runs. This pins the ⌈N/Q⌉ bound itself, not just the sort.
- `_latest_finished_close`:
  - `before` equal to the newest fixture date returns the bar before it (the
    in-progress day is never chosen);
  - `before` after every bar returns the newest bar;
  - an empty series returns `None`.
- `FilePriceFetcher` against temporary files with `monkeypatch.setenv`:
  - the variable unset or empty;
  - a missing file;
  - an undecodable file;
  - a wrong header, a short row, a bad date, a non-decimal close;
  - a repeated `(identifier, date)`, which is an error with its line number;
  - an absent symbol, which is `no_symbol`;
  - two dates for one symbol, where the later one wins;
  - a zero close passed through as a `Close`.
- `AlphaVantagePriceFetcher` with a fake `http_get` and a recording `sleep`:
  - a missing key gives `Err`, and `http_get` is never called;
  - `daily.json` gives a `Close` in EUR, with the URL asserted;
  - `unknown_symbol.json` gives `not_covered`;
  - throttled at the second of three symbols gives the first `Close`, the
    other two `transient`, and exactly two requests;
  - `sleep(1)` is called between requests only;
  - the requests go out in exactly the order given, which the fake asserts
    from the URLs it records;
  - `URLError` gives `Err(AlphaVantageUnreachable)`;
  - an HTML body gives `Err(UnexpectedAlphaVantageResponse)`;
  - `TESTKEY` appears in no `detail` and no error string.
- `plugin_manager` with `entry_points` patched to a mix of kinds:
  - each loader returns only its kind;
  - a neither-kind class raises `TypeError`;
  - a duplicate within a kind raises `ValueError` with the name
    interpolated, which is the `f`-string fix's regression test;
  - a name shared across kinds is fine.

**Use case and services:**

- `SetPriceSource`:
  - each of the four refusals, with the available plugins named;
  - binding twice leaves exactly one row, the second (spec);
  - an identical rebind adds no `OperationGroup`.
- `held_units`:
  - a fractional buy fully sold in pieces (`0.1 + 0.2 − 0.3`) is **not**
    held;
  - a transfer between two depots stays held;
  - it is kind-agnostic: EUR, whose net is nonzero once a trade has posted,
    is returned, and the security filter happens in `ListPriceTargets`.
- `ListPriceTargets`: grouping by plugin and symbol; two units on one
  binding; unbound units; a non-security held unit absent from both. From
  033: `request_order` equals `oldest_close_first` over the stored closes,
  with a unit that has no close and a shared binding whose units differ.
- `AppendPrices`, against a `session` with hand-built `PriceTargets` and
  `FetchedCloses`:
  - all four outcomes, and `previous` shown;
  - a second run writes nothing and adds no `OperationGroup`;
  - a plugin `Err` leaves its units unpriced and no rows, while another
    plugin's rows are written;
  - an uninstalled plugin's units are `Unpriced(UnknownPricePlugin)`;
  - a missing result gives `MissingCloseResult`;
  - an unrequested symbol appears in `ignored` and writes nothing;
  - each validation failure leaves its unit's rows unchanged and another
    unit priced in the same run;
  - a pair of units on one binding (§14.2): a rejected shared close leaves
    both unpriced while a third unit is priced; a valid shared close gives
    `already stored` for one and `priced` for the other;
  - `list-operations` shows one `create prices` per new row, in one group.
- `latest_close`: a fixture for each of the three outcomes; age 7 is
  `Fresh` and age 8 is `Stale` with the default; `max_age_days=1` moves the
  boundary.

**CLI** (`kohle.app.cli.cli.load_price_plugins` monkeypatched, as in the
importer CLI tests):

- `set-price-source`: success, and each refusal exiting non-zero with its
  message.
- `fetch-prices` with the real `FilePriceFetcher` and `KOHLE_PRICE_FILE`
  pointing at a temporary file:
  - priced, then a re-run where every unit reports `already stored`;
  - unbound only exits 0;
  - the variable unset exits 1, with the message per unit.
- The Alpha Vantage throttle scenario (§10.6) exits 1 with one row stored.
- The Alpha Vantage ordering scenario (§10.6): the unit with no stored close
  is priced and the one with an older close is `transient`.
- Nothing held prints `No held securities`.

**Migrations:** §4.4.

**Guards:** §11.
