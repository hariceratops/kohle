# [feat] Import a broker trade as a cash-to-instrument transfer

Adds the security row type and the second CLI account so a buy or sell posts
as one balanced entry between the cash account and the instrument account.

Depends on: 025, 026
Spec: `dev/specs/importer-plugins-for-assets.md`

## Acceptance Criteria

- A security row type carries `instrument_identifier`, `quantity` and
  `unit_price` as non-optional fields, plus date, description and
  `reference`.
- A test shows a plugin returning a security row without a price is rejected
  before any write.
- `import-statement <plugin> <cash-account> <instrument-account> <file>`
  posts each security row as one balanced entry: a buy debits the instrument
  account and credits cash; a sell the reverse.
- Security rows run no rule matching and write no classification row.
- An identifier with no matching `Unit` aborts the import and names it
  (hint: `add-unit <identifier> <name> security`).
- A nonexistent or non-postable (leaf-only rule) account aborts the import.
- A rejection on any row leaves the ledger and audit trail unchanged.
