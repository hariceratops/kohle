# Importer plugins for asset statements

## Overview

The statement-importer plugin contract is `import_statement(path) ->
Result[pd.DataFrame, ImportError]` with a fixed five-column cash schema. A
DataFrame of that shape cannot express "this row moved 10 units of an
instrument at 100 each", so broker statements have no way in. Worse, once
profit reporting derives FIFO lots by replaying lines, an asset movement that
arrives without a price does not raise — it silently produces wrong profit.
This replaces the contract with typed ledger lines so that a security movement
missing its price is not something a plugin author can express, and extends
the import use case and CLI to post broker trades as transfers between a cash
account and an instrument account — while the same statement's dividend,
interest and refund lines keep flowing through the existing cash path.
Deduplication moves onto the statement's own per-row transaction reference,
which the first target broker format carries.

## Goals

- Plugin contract returns typed per-row statement lines instead of a
  DataFrame. A security movement carries instrument identifier, quantity and
  unit price as non-optional fields; omitting the price is a type error at the
  plugin author's desk, not a wrong number in a report. Testable: a plugin
  that returns a security row without a price is rejected before any write,
  and the test suite contains that case.
- Cash movements keep today's meaning (quantity in the base currency at price
  1, signed direction, counterparty name/IBAN, free-text description) under
  the new types. Testable: the existing Deutsche Bank plugin and its import
  tests pass against the migrated contract with no change in resulting ledger
  rows.
- A broker trade row posts as one balanced entry over two accounts: the cash
  account and the instrument account. Both are named by the user on the CLI
  (`import-statement <plugin> <cash-account> <instrument-account> <file>`);
  nothing is matched automatically by IBAN or by broker account number.
- A broker plugin emits **both** row types the contract defines, not only
  security rows. Trades are security rows; a statement's non-trade cash
  lines — dividends, interest, refunds — are plain cash rows, the same type
  the Deutsche Bank plugin emits today. Testable: a broker fixture containing
  a buy, a sell and a dividend imports all three, the dividend landing as a
  cash credit on the CLI-named cash account.
- Each row's entry is deduplicated by a unique per-row reference supplied by
  the plugin: the statement's native transaction/trade reference where it has
  one, content-derived inside the plugin where the format has none (see
  Non-Goals). The reference is
  scoped to the target account, so the same reference on two different accounts
  is two different facts. Testable: importing the same file twice writes
  nothing the second time and reports zero entries imported.
- A row whose native reference is absent, or which duplicates the reference of
  another row in the same file, is treated as a malformed statement: the import
  is rejected loudly and nothing is written. Rows whose reference was already
  imported by a previous run are skipped, which is what makes re-import a
  no-op.
- Unknown instruments are refused, not invented. An instrument identifier
  (ISIN/WKN) with no matching `Unit` aborts the import and names the
  unresolved identifier, so the user declares it first (`add-unit IDENTIFIER
  NAME`; the kind defaults to security). Same for an account name that does not exist, or that is
  not postable under the leaf-only rule.
- A trade is a **transfer**, not an expense: it moves value from the cash
  account to the holding account. Both legs are named on the CLI, so a
  security row runs no rule matching and records no classification row at all.
- A cash row keeps today's behaviour exactly, whichever plugin emitted it: the
  CLI-named cash account is one leg, the counterpart leg is resolved by the
  rule engine and falls back to `unclassified-income` / `unclassified-expense`
  when no rule matches. A dividend or interest row is never refused for want
  of a rule — it posts, and `reclassify` fixes it later. Routing dividends to
  a dedicated income account is account-and-rule setup the user does with
  existing `add-account` / `add-rule` commands, not something this feature
  builds. Testable: a dividend row with no matching rule imports and lands
  against `unclassified-income`.
- An import is all-or-nothing. Any rejection — malformed row, unresolvable
  instrument or account, unbalanced entry, duplicate reference within the file
  — leaves the ledger byte-identical to before the run, including the audit
  trail. Testable: a statement whose last row is malformed imports none of the
  preceding rows.
- A failing plugin (unreadable or unparseable file) surfaces as a named error
  and writes nothing.

## Non-Goals

- **Non-base-currency cash and FX.** Assumed out of scope: target statements
  are EUR-denominated. A row in another currency is not a case this contract
  handles, and FX rates reopen the record-vs-compute question settled for
  securities prices.
- **Fees, commissions and taxes as their own lines.** v1 does not model them
  as separate postings. Whatever the statement reports as the cash movement is
  what lands.
- **A reference fallback in the contract or the use case.** The contract
  requires a reference on every row and the use case never derives one: no
  file-name+row-index or content-hash fallback lives there, and rows without a
  reference are rejected. A plugin whose format has no bank-assigned per-row
  reference (the Deutsche Bank CSV: its `Customer Reference` can be absent or
  `NOTPROVIDED` and its `Mandate Reference` repeats across collections) computes
  the reference from row content inside the plugin. That keeps today's
  behaviour, since rows identical in date, amount and description already
  collide on the unique constraint. Do not generalise a fallback mechanism in
  advance.
- **Automatic account matching.** Neither IBAN matching nor broker-account-number
  matching is extended or kept for the asset path; the user names both accounts.
- **Instrument master data.** No external lookup of ISIN to name, kind, or
  exchange; no auto-creation of units.
- **Income-type accounts and their rules.** Dividend/interest rows are in
  scope for the first broker plugin, but only as cash rows through the
  existing classification path. Declaring salary/dividend/interest accounts
  and the rules that route to them is the user's own setup via `add-account`
  and `add-rule`; this feature adds no account kind, no seeded accounts and no
  new classification mechanism.
- **Price fetching** (see `price-fetcher-plugin`) and **profit/position
  reporting** (see `portfolio-and-profit-reporting`). This brief only has to
  record movements such that a replay can be correct.
- **Corporate actions** — splits, mergers, in-kind dividends, spin-offs — and
  short positions, derivatives, options.
- **TUI import wiring** (see `tui-wiring`).
- **The default "unallocated" child operation.** Posting goes to whatever
  postable leaf the user names; creating a first envelope under an account
  that already has postings is its own piece of work.

## Technical Approach

- Python 3.12, `uv` project, existing `app` → `use_cases` → `services` →
  `infrastructure`/`domain` layering. Functions return `Result[T, E]`; domain
  errors are `Exception` subclasses used as values and not raised.
- The contract lives in `kohle/plugin/importer_plugin.py`. Replace the
  DataFrame return with a typed per-row payload — one row type for a cash
  movement, one for a security movement carrying `instrument_identifier`,
  `quantity`, `unit_price` — each row carrying date, description and the
  statement's native `reference`. The existing dtype-schema validation
  (`validate_df_schema`, `DataframeMissingColumn`) is superseded for this path
  by the types themselves.
- `ImportStatement` in `kohle/use_cases/journal.py` is the use case to extend:
  it already resolves the account, derives a per-row reference, filters
  already-present references via `existing_references_service`, and posts
  through `post_entry`. The reference derivation changes from hashing
  date/amount/description to using the plugin-supplied reference scoped by
  account id; the rest of the row loop gains the security branch.
- The row loop branches on row type, and only the security branch is new. The
  cash branch is today's code path unchanged (`journal.py:328-345,391-393`):
  one account from the CLI, counterpart from `match_rule`, automatic fallback
  to `unclassified-income` / `unclassified-expense`. Dividend, interest and
  refund rows from a broker statement go through that same branch — nothing
  about them is broker-specific, so no third row type and no second
  classification path.
- Instrument identity is `Unit.identifier` (unique, `UnitKind.security`).
  `JournalEntry.reference` (unique) remains the dedup column.
  `DuplicateJournalEntry` is the existing error for a collision.
- Atomicity needs no new machinery: a use case runs inside one `UnitOfWork`
  wrapping a single database transaction, and the `OperationGroup` audit trail
  rolls back with it. The requirement is stated so it stays true, not because
  it needs building.
- Plugins are discovered from the `kohle.plugins` entry-point group; the
  Deutsche Bank importer in `kohle/app/plugins/` is the migration's regression
  case, and the first broker plugin is the new one. That broker plugin's job is
  to map each statement line to the right row type — security row for a trade,
  cash row for a dividend, interest payment or refund — and it must cover both
  from the start, since a real broker statement carries both.
- The CLI command `import_statement` in `kohle/app/cli/cli.py` grows a second
  account argument.

## Open Questions

- None blocking. Three readings from the interview were put back to the user
  and confirmed, and are now stated as requirements above rather than left
  open: security rows skip the rule engine and write no classification row;
  an already-imported reference is skipped while a reference duplicated within
  one file aborts; and non-trade cash rows (dividends, interest, refunds) are
  in scope for the first broker plugin, carried by the cash row type and the
  existing classification machinery with no new mechanism.
- Whether the typed contract keeps a DataFrame available to plugin authors
  internally for parsing convenience is the plugin author's business, not the
  contract's — noted only so nobody reads "no DataFrame" as banning pandas
  inside a plugin.
