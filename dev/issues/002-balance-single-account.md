# [feat] Report a single account's balance per unit

There is currently no way to ask what an account holds — journal lines can
only be listed for a date range. Add `kohle-cli balance ACCOUNT` reporting
quantity per unit for one account.

Spec: `dev/specs/cli-record-and-balances.md`

## Acceptance Criteria

- `kohle-cli balance ACCOUNT` prints one row per unit the account holds.
- Quantity is debits minus credits, following the existing `is_debit`
  convention on `JournalLine`.
- An account with no journal lines reports an empty result, not an error.
- A base-currency total row is shown only when the account holds exactly one
  unit and that unit is the base currency; any other case shows per-unit
  rows only.
- Output uses `tabulate`, matching the existing `entries-in-period` command.
- The query lives in a new service, invoked by a new use case following the
  established `UnitOfWork` / `DbTransactionContext` pattern. The CLI holds
  no query logic.
