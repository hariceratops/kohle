# Price fetcher plugin

## Overview

To value a portfolio you need a current price for each held security. But a
recorded transaction must never depend on a live price source: if it did,
re-running an import later would produce different books. This feature adds a
second plugin kind, the price fetcher, and an explicit `fetch-prices` command
that appends daily closes to a price-history table. Reports read that table and
never fetch. The separation is structural, not a matter of discipline: nothing
on the recording path reads prices, and nothing on the reporting path writes
them. Each held security is bound declaratively to exactly one plugin and one
symbol. Plugins are split by source, not by asset class. The first two are
`alphavantage` (HTTP) and `file` (a local CSV, which also works offline). The
feature delivers the table, the binding, the fetch command, and one read
function that classifies a unit's latest close as fresh, stale or none.
Building the report that consumes that function belongs to
`portfolio-and-profit-reporting`.

## Goals

- **Fetching is explicit.** `fetch-prices` is the only thing that calls a
  price plugin. No report, balance or import calls one, directly or lazily.
  Testable: the recording and import paths contain no reference to the price
  table or to price plugins. Running every existing command with no price
  plugins installed changes no output.
- **Daily close, latest only.** Each request asks a plugin for the latest
  daily close of each symbol. History builds up only from repeated runs.
  Results are typed per symbol, either a close (date, price, currency) or
  `Unavailable` with a reason (`no_symbol`, `not_covered`, `transient`).
  Plugins never return DataFrames. A failure of the whole plugin is an `Err`
  value and is never raised. That covers being offline, a missing API key or
  file-path variable, and an unreadable file. Throttling is not a whole-plugin
  failure: see the `alphavantage` goal below.
- **Second plugin kind, same discovery.** Price plugins are registered in the
  `kohle.plugins` entry-point group alongside importers.
  `plugin_manager.load_plugins` learns to tell the two kinds apart; it stops
  raising `TypeError` for anything that is not a `StatementImporterPlugin`.
  Testable: with both kinds installed, `import-statement` still sees only
  importers, and `fetch-prices` sees only price plugins.
- **Core is plugin-agnostic.** Adding a plugin changes no core code. Testable:
  a third price plugin defined only in the test suite (a test-local entry
  point or registration) can be bound and fetched without touching
  `kohle/plugin/`, `kohle/use_cases/`, `kohle/services/` or the CLI.
- **Explicit symbol binding, one per unit.**
  `set-price-source UNIT PLUGIN SYMBOL` writes a ledger row binding a unit
  (by `Unit.identifier`) to exactly one (plugin, symbol). It refuses an
  unknown unit, a unit whose kind is not `security` (the existing
  `NotASecurityUnit` error), and an unknown price-plugin name, naming the
  available plugins. Running it again on a unit that is already bound replaces
  the binding; that is how a mistyped symbol is fixed or a unit moves to
  another source. Testable: after binding a unit twice, it has exactly one
  binding, the second. The binding is never guessed: no fuzzy search, no ISIN-to-ticker
  lookup. Alpha Vantage is keyed by ticker, not ISIN/WKN, which is why the
  symbol is explicit. Coverage is declared the same way: a unit Alpha Vantage
  does not carry is bound to `file`.
- **Grouping by binding, no fallback.** `fetch-prices` takes the units with a
  nonzero position (net quantity across all accounts) whose kind is
  `security` and groups them by bound plugin. Each plugin is asked only for
  its own symbols, once per run. A held security with no binding is reported
  as `unbound`. That is not an error and does not by itself make the exit code
  non-zero. Testable: an unbound held unit appears in the output as unbound,
  and the command exits 0 when that is the only gap.
- **Per-unit outcome report and exit code.** For each held security the
  output gives exactly one outcome:
  - priced by plugin X on date D, with the previous stored close shown
    alongside the new one;
  - already stored for D;
  - unpriced, with a reason (an `Unavailable` reason, a validation failure,
    or the plugin's error);
  - unbound.

  The exit code is non-zero if any bound unit ends unpriced. Testable: a
  plugin returning `Err` makes the command exit non-zero and writes no row
  for any unit bound to that plugin. Rows from the other plugins in the same
  run are still written.
- **Append-only, idempotent history.** Price rows are unique on
  (unit, date). If a fetched (unit, date) already exists it is skipped, never
  overwritten. Each row records the plugin it came from. No code path
  updates or deletes a price row. Testable: running `fetch-prices` twice in a
  row against an unchanged source writes nothing the second time, and every
  unit reports "already stored".
- **Core validation, uniform for every plugin.** Every result, including
  one from `file`, passes the same checks in core before it is written:
  - it answers a symbol that was requested, so it maps to a known, bound unit;
  - the price is strictly positive;
  - the date is not after today;
  - the currency is the base currency (EUR).

  A violation makes that unit unpriced with the reason named. Nothing partial
  is written for it, and the other units are unaffected. Testable: a zero
  price, a negative price, a future date and a non-EUR currency are each
  rejected with their own reason, and each leaves the table unchanged for
  that unit.
- **Read side for reporting.** A read function returns a unit's latest stored
  close with its date and source, classified against a staleness threshold:
  - `fresh`: there is a close no older than N days;
  - `stale`: the latest close is older than N days;
  - `none`: no close is stored.

  N defaults to 7 and is a parameter, not a constant. "No price" and "stale
  price" are distinct outcomes, never collapsed. Testable: the three outcomes
  are each produced by a fixture, and the boundary day is pinned in a test.
  Offline therefore means no fetch, and the reader still serves the last
  stored close, flagged stale once it ages past N.
- **`alphavantage` plugin.**
  - The API key comes from the environment variable `KOHLE_ALPHAVANTAGE_KEY`.
    A missing key is a named plugin error, not an exception and not a
    per-unit failure.
  - The free tier allows about 25 requests a day, so being throttled partway
    through a run is the normal case, not an edge case. When the limit hits,
    the plugin keeps the closes it has already fetched and returns
    `Unavailable(transient)` for every symbol it did not get to. This is not
    a whole-plugin `Err`, so the closes fetched before the limit are written.
    The command still exits non-zero, because bound units ended up unpriced.
    Testable: a recorded run that is throttled after the first symbol writes
    that symbol's close, reports the rest as transient, and exits non-zero.
  - **Accepted risk on currency.** Binding a symbol to `alphavantage` is the
    user's assertion that the symbol quotes in EUR. The plugin makes no extra
    request to check the currency, and the binding has no currency column. It
    reports EUR on every close it returns. Core's EUR check still applies to
    whatever currency a plugin result carries, but it cannot catch a symbol
    bound by mistake that actually quotes in another currency. Such a close is
    stored as if it were EUR.
  - Tests run against a fake or recorded HTTP layer. The suite makes no live
    network calls.
- **`file` plugin.** Reads a local CSV with columns `identifier,date,close`
  from the path in the environment variable `KOHLE_PRICE_FILE`. If the
  variable is not set, that is a named plugin error. `fetch-prices` has no
  path flag. `identifier` is the symbol bound via `set-price-source`, and
  closes are reported in EUR, as with `alphavantage`. For each
  requested symbol it returns that symbol's most recent row, keeping "latest
  close only" the same for every plugin. A symbol absent from the file is
  `Unavailable(no_symbol)`. A malformed or unreadable file is a plugin `Err`.
  It works with no network.

## Non-Goals

- **Prices in transaction recording.** Rejected in the ledger design and
  restated here because this is where the temptation reappears. Recorded
  journal lines keep the price they had at transaction time. Nothing
  backfills, revalues or validates them against the price table.
- **On-demand fetching during a report.** Rejected in favour of the explicit
  command, so that a report is a pure read of stored history.
- **Fallback chains.** No ordered plugin list per unit, no fall-through to
  another plugin when one has no price, no automatic retry against a second
  source. Rejected by the user: a unit has one binding, and changing source
  means changing the binding.
- **A manual price-entry command.** No `set-price` and no `manual` source.
  The `file` plugin is the only hand-entered path, by explicit decision.
- **Price correction.** Because history is append-only and there is no manual
  entry, v1 has no way to correct a wrong stored close. A bad row stays.
- **Deviation warnings.** No "price moved more than X%" check and no `--yes`
  confirmation in v1. Explicitly deferred.
- **FX and non-base currencies.** A non-EUR close is a per-unit failure, as in
  the importer spec. Converting it would reopen the record-vs-compute
  question.
- **Physical gold and other commodity units.** Units of kind `commodity` are
  deferred. They will be added later with a price source chosen at that time.
  The user believes Alpha Vantage supports commodities; this has not been
  verified. Gold held through an ETF is a `security` and is in scope.
- **Backfill, date ranges and intraday prices.**
- **Reports, profit, net-worth output, or any consumer of the read function**
  (see `portfolio-and-profit-reporting`).
- **Instrument master data.** No ISIN-to-ticker resolution, no symbol search,
  no auto-creation of units or bindings.
- **TUI wiring** (see `tui-wiring`).
- **Corporate actions.** Splits and similar events that make a historical
  close incomparable are not adjusted for.

## Technical Approach

- **Stack and conventions.**
  - Python 3.12, `uv` project, layered `app` → `use_cases` → `services` →
    `infrastructure`/`domain`.
  - Functions return `Result[T, E]`. Plugin and domain errors are `Exception`
    subclasses used as values and never raised. The contract module follows
    `kohle/plugin/importer_plugin.py`: a leaf module with frozen, slotted,
    keyword-only dataclasses and no dependency on the services layer.
- **Contract.** New module `kohle/plugin/price_plugin.py`:
  - a `PriceFetcherPlugin` ABC with a `name` property and one method taking
    the list of symbols to fetch;
  - the method returns `Result[<per-symbol mapping to Close | Unavailable>,
    PriceFetchError]`;
  - `Close` carries `price_date`, `price` (`Decimal`) and `currency`;
  - `Unavailable` carries the reason.

  The design settles the exact shape.
- **Plugin discovery.** `kohle/plugin/plugin_manager.py` currently returns
  `dict[str, StatementImporterPlugin]` and raises `TypeError` for anything
  else. It must partition entry points by kind, so each caller gets only
  plugins of its own kind. The `import_statement` and
  `list_importer_plugins` call sites in `kohle/app/cli/cli.py` keep seeing
  importers only. The duplicate-name `ValueError` in that function has a
  misplaced f-string prefix (`"fDuplicate plugin name: {instance.name}"`);
  fix it while touching the function.
- **Plugin files.**
  - The new plugins live in `kohle/app/plugins/` beside the two importers
    and are registered under `[project.entry-points."kohle.plugins"]` in
    `pyproject.toml`.
  - There is no HTTP client in the dependencies. The design chooses between
    stdlib `urllib.request` and adding one. Either way, the HTTP call sits
    behind a seam the tests can replace.
  - Alpha Vantage reports throttling in the response body rather than through
    the HTTP status. The plugin has to recognise that body and switch to
    returning `Unavailable(transient)` for the remaining symbols.
  - **Design must confirm the Alpha Vantage endpoint.** It has to return a
    finished daily close, so that a trading day still in progress is never
    stored as that day's close. This is left to the architect.
- **Price table.**
  - The `Price` model (`kohle/domain/models.py`, table `prices`) and its table
    already exist, created in migration
    `alembic/versions/7f3c1d9a2b40_multi_unit_ledger.py`. Nothing uses them
    yet.
  - Its constraint `uq_price_unit_date_source` is on
    (`unit_id`, `price_date`, `source`). That allows two closes for one day
    and contradicts the requirement above.
  - A new migration off the current head (`a1cebfe54f33`) replaces it with a
    unique (`unit_id`, `price_date`). `source` stays a column, holding the
    plugin name.
  - `tests/test_migration_downgrade.py` already checks for the `prices`
    table and must keep passing.
  - No currency column is needed, because only EUR rows are ever written.
- **Binding table.** A new model and table, written by `set-price-source`,
  with a unique `unit_id` and columns for the plugin name and symbol. There is
  no currency column. A second `set-price-source` for the same unit replaces
  the existing binding instead of adding a row. It goes in the same migration
  or one beside it. The kind check uses the existing `NotASecurityUnit` from
  `kohle/domain/domain_errors.py`.
- **Staleness threshold.** N is a parameter of the read function, default 7.
  How a user sets it is left to `portfolio-and-profit-reporting`, which owns
  the read function's only caller.
- **Base currency.** `BASE_CURRENCY = "EUR"` lives in
  `kohle/use_cases/journal.py`. Validation compares against that constant,
  not a second copy.
- **Units and holdings.**
  - Units are looked up through `get_unit_by_identifier_service`
    (`kohle/services/unit_services.py`), and `UnitNotFoundError` is the
    existing error for an unknown one.
  - "Held" means a nonzero net quantity for the unit summed over all journal
    lines (debit positive, credit negative). This is the same fold
    `aggregate_by_unit` in `kohle/use_cases/journal.py` performs per account,
    applied across all accounts.
- **Where the network call sits.** Plugin calls happen outside any database
  transaction, following the `import_statement` precedent in
  `kohle/app/cli/cli.py`: the plugin is called first and the use case
  receives its result.
  - One `UnitOfWork` reads the held, bound units grouped by plugin.
  - The plugins are called.
  - A second `UnitOfWork` validates and appends.

  Price rows go through the services layer like every other write, so they
  appear in the `Operation` audit trail.
- **Atomicity is per unit, not per run.** One unit's failure must not roll
  back another unit's valid close. This deliberately differs from the
  importer's all-or-nothing rule: price rows are independent facts, while a
  statement is one document.
- **Tests and CLI.**
  - Tests use the existing CLI test pattern (`tests/test_cli.py`,
    `tests/test_import_statement_cli.py`) and fake plugins. Alpha Vantage
    responses are recorded fixtures under `tests/fixtures/`.
  - The new CLI commands `fetch-prices` and `set-price-source` go in
    `kohle/app/cli/cli.py`.

## Open Questions

- None blocking. All seven questions from the first draft were answered by
  the user and are now written into the requirements above:
  - throttling keeps the closes already fetched;
  - binding a symbol asserts that it quotes in EUR;
  - the file path comes from `KOHLE_PRICE_FILE`;
  - commodities are deferred, and non-security units are refused;
  - rebinding replaces the existing binding;
  - how the staleness threshold is configured is left to reporting.

  Confirming which Alpha Vantage endpoint gives a finished daily close is a
  design task, recorded in Technical Approach, not an open requirement.
