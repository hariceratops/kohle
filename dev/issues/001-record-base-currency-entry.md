# [feat] Record a two-line base-currency entry from the CLI

The ledger can currently only be written to by importing a bank statement.
Add `kohle-cli record` for the common case — a two-line entry denominated in
the base currency, covering an expense or a transfer between accounts.

Spec: `dev/specs/cli-record-and-balances.md`

## Acceptance Criteria

- `kohle-cli record ENTRY_DATE DESCRIPTION QUANTITY --from CREDIT_ACCOUNT
  --to DEBIT_ACCOUNT` posts a balanced two-line journal entry.
- `--from` is credited and `--to` is debited, both in the base currency at
  `unit_price` 1.
- Posting routes through the existing `RecordJournalEntry` use case; the CLI
  reimplements neither the balance-by-value check nor the leaf-only posting
  rule.
- The entry reference is system-generated and is never accepted as CLI input.
- An unknown account name produces a clear error message, not a traceback.
- Posting to an account that has children fails with the existing
  `PostingToNonLeafAccount` error, surfaced readably.
- Steps 2 through 4 of the spec's cash-envelope scenario are executable end
  to end: the withdrawal into `Cash:Unallocated`, the sibling-to-sibling
  allocation into an envelope, and a spend out of that envelope.
