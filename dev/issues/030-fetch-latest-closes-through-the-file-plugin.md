# [feat] Fetch latest closes through the file plugin

`fetch-prices` appends the latest daily close for each held, bound security to
an append-only price history, with the `file` plugin as the first real source.
It works offline and proves the whole fetch path before any network source
exists.

Depends on: 029
Spec: `dev/specs/price-fetcher-plugin.md`

## Acceptance Criteria

- A new migration, off 029's revision, changes `prices` uniqueness from
  (`unit_id`, `price_date`, `source`) to (`unit_id`, `price_date`);
  `source` holds the plugin name. `tests/test_migration_downgrade.py` still
  passes.
- Held means a nonzero net quantity across all accounts and `UnitKind.security`.
  Held units are grouped by bound plugin; each plugin is called once per run
  with only its own symbols. No fallback to another plugin.
- The `file` plugin reads `identifier,date,close` from the path in
  `KOHLE_PRICE_FILE`, returns each requested symbol's most recent row in EUR,
  and returns `Unavailable(no_symbol)` for a symbol absent from the file. An
  unset variable or an unreadable or malformed file is a named plugin `Err`.
  It is discovered through the `kohle.plugins` group.
- Plugin calls happen outside any database transaction: one `UnitOfWork` reads
  the held, bound units, the plugins are called, a second `UnitOfWork` appends.
  Price rows are written through the services layer and appear in the
  `Operation` audit trail.
- Output gives exactly one outcome per held security: priced by plugin X on
  date D with the previous stored close shown alongside; already stored for D;
  unpriced, with a reason (an `Unavailable` reason, or the plugin's `Err`);
  or unbound. A held security with no binding is not an error.
- A plugin `Err` leaves every unit bound to it unpriced with the plugin's
  error as the reason, and writes no row for them; rows from other plugins in
  the same run are still written.
- The exit code is non-zero if any bound unit ends unpriced.
- Running `fetch-prices` twice against an unchanged file writes nothing the
  second time and every unit reports "already stored". No code path updates
  or deletes a price row.
- An unbound held unit appears as unbound and the command exits 0 when that
  is the only gap.
