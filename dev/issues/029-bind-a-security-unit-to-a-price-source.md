# [feat] Bind a security unit to a price source

`set-price-source UNIT PLUGIN SYMBOL` declares where a held security's price
comes from, end to end: the price-plugin contract, plugin discovery by kind,
and the binding table. No fetching yet; this slice proves a second plugin kind
can exist and that coverage is declared, never guessed.

Depends on: none
Spec: `dev/specs/price-fetcher-plugin.md`

## Acceptance Criteria

- `kohle/plugin/price_plugin.py` defines the `PriceFetcherPlugin` contract:
  a `name`, one method taking the symbols to fetch and returning
  `Result[mapping of symbol to Close | Unavailable, PriceFetchError]`. `Close`
  carries date, `Decimal` price and currency; `Unavailable` carries a reason
  (`no_symbol`, `not_covered`, `transient`). No DataFrames.
- `plugin_manager.load_plugins` partitions entry points by kind and no longer
  raises `TypeError` for a non-importer. With both kinds installed,
  `import-statement` sees only importers and `set-price-source` sees only
  price plugins.
- The duplicate-plugin-name error message is formatted correctly (the
  misplaced `f` prefix is fixed).
- A new migration off head `a1cebfe54f33` adds a binding table with a unique
  `unit_id` and columns for plugin name and symbol; no currency column.
- `set-price-source` binds a unit by `Unit.identifier`. It refuses an unknown
  unit (`UnitNotFoundError`), a unit whose kind is not `security`
  (`NotASecurityUnit`), and an unknown plugin name, naming the available ones.
- Running it again for a bound unit replaces the binding: after binding twice
  the unit has exactly one binding, the second.
- Tests use a test-local fake price plugin; no real plugin is needed.
