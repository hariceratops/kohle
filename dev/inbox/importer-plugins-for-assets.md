# Importer plugins for asset statements

## Goal

Extend the existing statement-importer plugin contract so that broker and asset
statements land as ledger lines carrying instrument, quantity and price — not
just cash rows — and so that a plugin author cannot accidentally omit the price.

The problem behind it: the contract today is
`import_statement(path) -> Result[pd.DataFrame, ImportError]`, and a DataFrame
has no way to express "this row moved 10 units of an instrument at 100 each".
The existing Deutsche Bank plugin only has to think about cash. Once profit
reporting derives FIFO lots by replaying lines, a price missing from an asset
movement does not raise anything — it silently produces wrong profit. The
contract is the right place to make that impossible.

## Considerations surfaced

Deduplication needs carrying over. The old `Transaction` model had a unique
`hash` column so re-importing a statement was idempotent. The new
`JournalEntry.reference` unique constraint looks like its replacement, but the
importer is what has to generate a stable reference, and it now spans multiple
lines rather than one row.

Account matching is currently by IBAN, and broker accounts may not have one —
they tend to have an account number in a broker-specific format. Since `iban` is
now nullable, matching cannot lean on it alone.

Imported rows should land in the "unallocated" child of the target physical
account rather than the parent, per the leaf-only posting rule in the ledger
design.

Instrument identity wants to be ISIN or WKN — `Instrument.identifier` already
exists with a unique constraint, so the importer needs to resolve or create
instruments as it goes.

## Directions rejected

None yet — this brief has not been argued through in the way the ledger design
has.

## Open questions

- Does the plugin keep returning DataFrames, or move to typed ledger lines? The
  DataFrame is convenient for parsing but cannot carry the guarantee that asset
  movements have prices.
- How are broker accounts matched to Kohle accounts without an IBAN?
- Is `JournalEntry.reference` the dedup key, and who generates it — plugin or
  core?
- On a partially malformed statement, is the whole import rejected or does it
  proceed per-line with the bad rows reported?
- Does the importer resolve unknown instruments automatically, or refuse and
  make the user declare them first?
