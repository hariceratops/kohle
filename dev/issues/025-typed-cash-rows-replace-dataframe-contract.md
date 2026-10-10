# [feat] Typed cash rows replace the DataFrame plugin contract

The importer plugin contract returns a fixed-schema DataFrame, which cannot
express asset movements. This slice swaps it for typed per-row lines, with
only the cash row type for now, and migrates the Deutsche Bank plugin onto it
as the regression case.

Depends on: none
Spec: `dev/specs/importer-plugins-for-assets.md`

## Acceptance Criteria

- `import_statement(path)` returns typed per-row lines (date, description,
  counterparty name/IBAN, signed quantity in base currency at price 1, native
  `reference`) instead of a DataFrame; `validate_df_schema` is no longer
  used on this path.
- `ImportStatement` consumes the typed rows; the cash branch behaves exactly
  as today (CLI-named account, `match_rule`, fallback to
  `unclassified-income` / `unclassified-expense`).
- The existing Deutsche Bank plugin tests pass with no change in resulting
  ledger rows.
- An unreadable or unparseable file surfaces as a named error and writes
  nothing.
- Risk to settle in design: the Deutsche Bank statement exposes only
  `Customer Reference` / `Mandate Reference`, which may be absent or
  non-unique per row. If it has no usable native reference, this needs a spec
  revision (the spec forbids a hash fallback) — raise it, don't invent one.
