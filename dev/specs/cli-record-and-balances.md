# CLI record and balances

## Overview

The ledger can currently only be written to by importing a bank statement,
and can only be read back by listing journal lines within a date range for
one account. This slice adds the missing halves: a way to record a journal
entry by hand from the CLI, and a way to ask what an account holds. Both
build entirely on existing machinery — `RecordJournalEntry` already
validates and posts entries, and `account_lines_service` already fetches an
account's lines — this slice is CLI surface plus one new balance-rollup use
case, not new ledger mechanics.

## Goals

- `kohle-cli record` lets a user post the common two-line entry (a transfer,
  an expense, a purchase of a non-base unit) in one command, without
  hand-writing every line.
- `kohle-cli record-split` lets a user post an arbitrary n-line entry (e.g. a
  shared expense split three ways) by repeating one flag per line.
- Both commands route through the existing `RecordJournalEntry` use case, so
  balance-by-value and leaf-only-posting are enforced exactly once, in
  `validate_lines` — the CLI adds no validation of its own.
- `kohle-cli balance ACCOUNT` reports what an account holds: quantity and
  average cost per unit, rolled up recursively if the account has children.
- `record` must express a sale as readily as a purchase — see the
  cross-unit constraint below. A workflow that makes selling harder than
  buying pushes sales onto `record-split`, and a sale recorded without its
  price and date does not raise an error later, it silently produces wrong
  FIFO profit (the profit-reporting brief depends on sales carrying
  quantity, price and date exactly as purchases do).
- **Testable, primary scenario — cash envelopes.** This is the user's real
  workflow and exercises `record`, `balance`, and the account tree
  together:
  1. The user creates the tree by hand, with the existing `add-account
     --parent` command: `Cash`, and under it three leaf children —
     `Unallocated`, `Groceries`, `Eating out`. `Cash` itself is never
     posted to, only rolled up — see the note below on why.
  2. Withdraw a lump sum ahead of time: `record` credits `Checking`, debits
     `Cash:Unallocated` (both EUR, no `--unit`/`--price` needed).
  3. Allocating a quota to an envelope is a sibling-to-sibling transfer:
     `record` credits `Unallocated`, debits `Groceries` (or `Eating out`).
     It nets to zero at `Cash`, which is what keeps the rollup meaningful.
  4. A spend credits the envelope it came from and debits the corresponding
     expense account.
  5. `balance Cash` rolls up across all three children (`Unallocated`,
     `Groceries`, `Eating out`); `balance Groceries` shows that envelope
     alone.
  6. Overspending an envelope shows up as its balance going negative —
     `balance` reports this like any other number; nothing in the ledger or
     this slice blocks a spend that would take an envelope negative. A
     negative balance is the signal the envelope is over budget, not an
     error condition.

  **`Cash` holding no postings of its own is not a workaround, it is the
  account tree's rule applied correctly.** Only leaf accounts may be
  posted to (`validate_lines` / `account_has_children_service` in
  `kohle/use_cases/journal.py`); the moment `Cash` gained children it
  stopped being postable, and posting to it would make "parent balance is
  the sum of its children" false without any error surfacing anywhere.
  `Unallocated` exists precisely so the lump sum has a leaf to land on.

  This scenario assumes the user has chosen to model cash as an account
  tree with envelope children — an account-structure *convention*, not a
  code feature this slice builds. `balance`'s usefulness for budgeting
  depends on the user adopting it and creating `Unallocated` themselves
  (see Non-Goals for why that creation isn't automated in this slice), not
  on anything enforcing it.
- **Secondary example — cross-unit purchase**, still the clearest
  illustration of quantity-versus-value balancing: `record 2026-03-06 "Buy
  ETF" 10 --from Checking --to Broker --unit IE00B4L5Y983 --price 100`
  posts a balanced two-line entry (1000 EUR credited from Checking, 10
  units debited to Broker at price 100), and `balance Broker` afterward
  shows one row: `10 IE00B4L5Y983 @ avg cost 100`.

## Non-Goals

- FIFO lot-based profit/realized-gain reporting — belongs to
  `portfolio-and-profit-reporting.md`, a later slice.
- Any live or fetched price integration — no price fetcher exists yet;
  balances use only the `unit_price` already recorded on each line.
- Editing or voiding a recorded entry — the ledger stays append-only in this
  slice; correction is a reversing entry via `record`/`record-split`.
- A "show one entry by reference/id" lookup command — `entries-in-period`
  already covers inspection.
- A user-supplied `--reference` flag on `record`/`record-split`. This was
  raised specifically as a way to serve the cash-envelope quota use case,
  and is deliberately not the answer: the quota is already served by
  virtual accounts and `balance`, which tell the user more than a reference
  string would. A user-chosen reference only earns its place for matching
  an entry to a paper receipt, and only alongside a lookup-by-reference
  command — those two belong together as a later slice, not as a lone flag
  here. Reference stays system-generated, as specified above.
- Non-EUR cash / FX handling.
- New account or unit management commands — `add-account`, `add-unit`,
  `list-accounts`, `list-units` already exist and are untouched. In
  particular, the cash-envelope scenario's `Unallocated` child is created
  by the user via existing `add-account --parent`, not by any new command.
- **Auto-creating a default `Unallocated` child when an account gains its
  first sibling child.** Considered and rejected for this slice. It's the
  eventual convenience — it would have let step 1 of the cash-envelope
  scenario happen implicitly — but it drags in the stranded-postings
  problem: an account that already has journal lines posted to it directly
  stops being a leaf the moment it gets a first child, and those existing
  lines need to move onto the new default child or the rollup breaks
  silently. That's a migration operation on existing data, not CLI surface
  work, and is well outside this slice. Already tracked as an open
  question in `dev/inbox/kohle-ledger-vision.md` ("The default
  'unallocated' child is not built"). This PRD's cash-envelope scenario is
  the first concrete workflow to actually hit that gap, which is worth
  noting as evidence for when it stops being deferrable — a hand-built
  `Unallocated` child is a real workaround the user has to remember to do,
  every time, not a one-off.
- CSV/spreadsheet-exportable output — a `tabulate` table, matching
  `entries-in-period`, is enough.
- TUI wiring — `kohle-tui` stays unwired.
- Net worth or any cross-unit valuation total — deferred until a price feed
  exists.

## Technical Approach

- Python 3.12, Click, matching the existing command style in
  `kohle/app/cli/cli.py` (`click.group`, `click.argument`/`click.option`,
  `Result` handling printed via `click.echo`, tables via `tabulate`).
- All quantities and prices are `Decimal`.

**`record` (shorthand, two lines):**

```
kohle-cli record ENTRY_DATE DESCRIPTION QUANTITY --from CREDIT_ACCOUNT --to DEBIT_ACCOUNT [--unit UNIT] [--price PRICE]
```

- `--unit` defaults to the base currency (EUR); `--price` defaults to 1.
- **Constraint, not mechanism — the shorthand must express a sale as
  directly as a purchase.** When `--unit` differs from base currency, one
  side carries QUANTITY of `--unit` at `--price` and the other side is
  derived in base currency so the entry balances by value; that much is
  fixed. Which side (`--from`/credit vs `--to`/debit) is allowed to carry
  the non-base unit — and whether that is fixed per-flag or inferred, e.g.
  from which of `--from`/`--to` the user attaches `--unit` to — is a flag
  design question left to the architect. A design that hardcodes "`--to`
  always carries the non-base unit" fails this constraint, because it can
  express a purchase (units arrive via `--to`) but not a sale (units leave
  via `--from`) without resorting to `record-split`. Whatever shape is
  chosen must make both directions equally reachable through `record`.
- If `--unit` is the base currency (the default, or given explicitly), both
  sides use QUANTITY at unit_price 1 — a same-unit transfer or expense.
  Passing `--price` together with a base-currency `--unit` is rejected with
  a clear error (it cannot mean anything, since value is trivially equal on
  both sides at unit_price 1; silently ignoring it risks masking a user
  mistake about which case they meant). **Flagged as a decision open to
  revision** during design, not a verbatim user answer.
- Reference is always system-generated (e.g. a uuid), never a CLI input —
  hand-entry has no re-import idempotency need the way statement import
  does, and no reference-lookup command exists in this slice to make a
  user-chosen reference pay off.
- Both `--from`/`--to` account names and `--unit` must already exist; no
  auto-vivification (unlike `ImportStatement`'s unclassified-bucket
  creation). Unknown names produce a clear CLI error, not a traceback.

**`record-split` (general, n lines):**

```
kohle-cli record-split ENTRY_DATE DESCRIPTION --line ACCOUNT:QUANTITY:UNIT:PRICE:SIDE [--line ...]
```

- `SIDE` is `debit` or `credit`. At least two `--line` flags required
  (`RecordJournalEntry`'s `EmptyEntry` check already enforces this).
- No derivation: every line is given in full, in the shape `LineSpec`
  already expects. Balance-by-value is still checked by the shared use
  case, exactly as for `record` and for statement import.

**`balance ACCOUNT` (new use case, new service):**

- Resolves `ACCOUNT`, walks its subtree (empty subtree for a leaf), and
  aggregates `JournalLine`s across every account in that subtree, grouped by
  unit. Needs a recursive-descendant query against `Account.parent_id` —
  new, since `account_lines_service` only fetches one account's own lines.
- Per unit: quantity (debit lines add, credit lines subtract, per the
  existing `is_debit` convention) and average cost, weighted by quantity,
  computed from each contributing line's `unit_price`. Explicitly average
  cost, not FIFO lots.
- One row per unit, always — never combined, since combining across units
  needs a price this slice doesn't have. A base-currency total line is
  shown only when the subtree holds exactly one unit and that unit is the
  base currency; any other case shows only per-unit rows.
- Whether a non-rolled-up ("this account's own lines only") flag exists
  alongside the default rolled-up view is left to the architect — optional,
  not required for this slice.
- Output via `tabulate`, matching `entries_in_period`.

**Integration points:** `RecordJournalEntry` (`kohle/use_cases/journal.py`),
`LineSpec`/`add_journal_entry_service` (`kohle/services/journal_services.py`),
new balance use case + service following the same `UnitOfWork` /
`DbTransactionContext` pattern, `Account` tree (`kohle/domain/models.py`),
CLI wiring in `kohle/app/cli/cli.py`. Layering stays `app -> use_cases ->
services -> infrastructure/domain` per `AGENTS.md`; the CLI adds no
validation logic of its own.

## Open Questions

- **How `record` expresses which side carries a non-base unit** (and
  therefore how it expresses a sale vs. a purchase) is left to the
  architect. The Goals and Technical Approach sections state this as a hard
  constraint — both directions must be reachable through `record` — but
  deliberately do not fix the flag shape.
- Whether to reject or ignore `--price` when combined with a base-currency
  `--unit` on `record` is flagged as a decision open to revision during
  design, not a user-confirmed contract.
- Whether `balance` needs a flag to see an account's own direct lines
  without the rollup is left open as an optional nice-to-have.

Everything else raised during the interview was resolved; no other open
questions remain.
