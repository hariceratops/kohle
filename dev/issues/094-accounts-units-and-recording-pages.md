# [feat] Accounts and units, and Recording entries pages

Carve the account, unit and entry-recording material out of the README into two concept pages.

Depends on: 091

## Acceptance Criteria

- `docs/accounts-and-units.md` and `docs/recording-entries.md` cover accounts and units, recording entries and reading the ledger.
- Every `kohle-cli` invocation is a checked example and passes.
- Explanations a generator cannot produce stay (why entries are balanced, how units behave); option and default lists defer to the generated reference.
- Both pages are in the nav and the strict build passes.
