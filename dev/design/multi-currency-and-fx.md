# Design: Multi-currency accounts and FX

Spec: `dev/specs/multi-currency-and-fx.md` (frozen)
Issues: `dev/issues/107`–`125`
Precedents, cited by short name:

- **PF**: `dev/design/price-fetcher-plugin.md`
- **MV**: `dev/design/market-value-reporting.md`
- **PP**: `dev/design/portfolio-and-profit-reporting.md`

Layering per `AGENTS.md` stays `app -> use_cases -> services ->
infrastructure/domain`. Only services touch a `Session`. Functions return
`Result[T, E]`; domain errors are `Exception` subclasses used as values.

Gaps and contradictions found in the spec are collected in §13. Where the
design had to choose behaviour the spec leaves open, the choice is made,
marked there, and left for the user to confirm. Changes to issue scope and
order are in §12.

---

## 1. Summary of the shape

| File | Change | Issue |
|---|---|---|
| `kohle/domain/models.py` | `BASE_CURRENCY` moves here (§2.7). `JournalLine` gains `cost` and `price_unit_id` (§2.1), a `price_unit` relationship, and `foreign_keys=[unit_id]` on `unit`. `JournalLine.value` returns `cost` when it is set. `Price.currency` and `PriceBinding.quote_currency`, both defaulting to `"EUR"` (§5). | 107, 111, 113 |
| `kohle/use_cases/accounts.py` | `PEOPLE_ROOT`, `BalanceSheetAccounts` and `balance_sheet_accounts` move here from `journal.py`, unchanged (§2.7). | 113 |
| `kohle/services/journal_services.py` | `LineSpec` gains `cost` and `price_unit_id`; `LineSpec.value` honours `cost`. `add_journal_entry_service` writes both. New `currency_lines_service` (§3.5). `query_lines_by_period_service` joined-loads `price_unit`. | 111, 113, 114 |
| `kohle/use_cases/journal.py` | Re-exports the moved names. `Total` and `CurrencySide` inputs; `CrossUnitLine.price` and `LineInput.unit_price` become `Decimal \| Total`; `LineInput.price_currency`. `validate_lines` balances per price currency (§2.2). `RecordSimpleEntry` and `RecordSplitEntry` build the new forms (§6). `UnitBalance.kind`. `aggregate_by_unit` and `aggregate_by_unit_through` take `costs`. `account_balance` and `net_worth_lines` fetch them through `lots.line_costs` (§2.4). | 111–117, 119 |
| `kohle/use_cases/lots.py` | `Lot.unit_cost` becomes an exact `Fraction` (§3.2). The replay links the units of one entry: currencies first, then the lines they paid for, then securities (§3.3). `_foreign_currency`; `_replayed` widened; a `lots_for` parameter on `replay`. `LotReplay.costs`, `FifoHolding.kind`. New `line_costs` (§3.5). | 111, 113–117 |
| `kohle/domain/domain_errors.py` | New errors (§3.6, §5, §6); `UnbalancedEntry` names a currency; `NonBaseCurrency` is reworded; `BalanceError` and `BudgetError` gain `LotError`. | 107, 108, 111–117 |
| `kohle/plugin/price_plugin.py` | A concrete `fetch_bound_closes` method that core calls (§5.3). | 107 |
| `kohle/services/price_services.py` | Bindings carry the quote currency; prices carry their currency. | 107 |
| `kohle/use_cases/prices.py` | `SetPriceSource` takes a quote currency and binds currency units. `ListPriceTargets` adds held currency units and the quote currencies of held securities. `validate_close` compares against the binding. `AppendPrices` checks each unit and stores the currency. | 107, 108 |
| `kohle/use_cases/reporting.py` | `_quote` reads a close and its rate (§8.1). Valued rows gain `rate`; `valuation_status`; `Subtotal`, `subtotals`, `holding_currencies`, `PositionsReport`; `ValuedNetWorthReport.subtotals`. | 120–123 |
| `kohle/use_cases/budgeting.py` | Spending reads lot-derived costs. | 114 |
| `kohle/app/cli/cli.py` | New `record` flags (`--total`, `--currency`, `--rate`), the `record-split` price grammar, `set-price-source --currency`, the currency in `fetch-prices`, a `priced in` column in `entries-in-period`, the `quoted in` column and rate formatting, and the subtotal tables (§6, §8). | 107, 111–122 |
| `kohle/app/plugins/kohle_ecb_price_fetcher.py` | **new**, `ecb` (§7.2). | 109 |
| `kohle/app/plugins/kohle_nse_price_fetcher.py` | **new**, `nse` (§7.3). | 110 |
| `kohle/app/plugins/kohle_file_price_fetcher.py` | Optional `currency` column. | 107 |
| `kohle/app/plugins/kohle_alphavantage_price_fetcher.py` | Reports the binding's quote currency via `fetch_bound_closes`. | 107 |
| `pyproject.toml` | Entry points `ecb` and `nse`. No new dependency. | 109, 110 |
| `kohle/db/migrations/versions/` | Three migrations (§9). `HEAD_REVISION` in `kohle/db/schema.py` follows each. | 107, 111, 113 |
| `docs/` | `prices.md`, `recording-entries.md`, `reports.md`, `accounts-and-units.md`, `writing-plugins.md`. | all |

**Import direction after the change.**

```
cli ──► reporting ──► lots ──► accounts
 │          │  ▲        └────► domain (BASE_CURRENCY)
 │          │  └── journal ──► lots         (line_costs, for the fold)
 │          └───► prices ──► journal
 ├────► budgeting ──► journal, lots
 └────► splitting ──► journal
```

- `lots.py` no longer imports `journal.py`. That is what lets `journal.py`
  import `lots.py` (§2.7).
- `lots.py` still imports nothing from `prices` or `reporting`. The guard in
  `tests/test_price_guards.py` keeps holding it, and `journal`, `budgeting`
  and `splitting` reach it only transitively.

---

## 2. Lines with no euro figure on their face (decision 1)

### 2.1 The line shape

Two nullable columns on `journal_lines`:

| Column | Meaning |
|---|---|
| `cost` `Numeric(20, 8)` | The line's whole value in its price currency, stated on the entry. When set, it is authoritative, and `unit_price` holds `cost / quantity` to the column's scale for display only. |
| `price_unit_id` → `units.id` | The currency `unit_price` and `cost` are in. `NULL` is the base currency, which every existing row is. A non-base currency here means the line has no euro figure: its euro value comes from the lots. |

`JournalLine.value` and `LineSpec.value` become "the face value": `cost` if
set, else `quantity * unit_price`, in the price currency. Every existing row
has both columns `NULL`, so every existing value is unchanged.

The entry forms, as lines:

| Form | Lines (unit, quantity, figure, price currency) |
|---|---|
| Remittance, 1,000 EUR for 90,000 INR (111) | `Girokonto cr EUR 1000 @1` · `IndianBank dr INR 90000 cost=1000` |
| Opening, INR or a security (112) | `Opening cr EUR 1000 @1` · `IndianBank dr INR 90000 cost=1000` (or `Demat dr INFY 100 cost=1500`) |
| Purchase paid in INR (113) | `DematCash cr INR 120000 @1 [INR]` · `Demat dr INFY 100 @1200 cost=120000 [INR]` |
| Expense paid in INR (114) | `IndianBank cr INR 1500 @1 [INR]` · `Groceries dr INR 1500 @1 [INR]` |
| Reconversion (115) | `IndianBank cr INR 70000 cost=800` · `Girokonto dr EUR 800 @1` |
| Sale for INR at a rate (116) | `Demat cr INFY 50 cost=676` · `DematCash dr INR 65000 @0.0104 cost=676` |
| Dividend in INR at a rate (116) | `Dividends cr INR 2000 @0.0104 cost=20.80` · `DematCash dr INR 2000 @0.0104 cost=20.80` |
| Move between own accounts (117) | `IndianBank cr INR 50000 @1 [INR]` · `DematCash dr INR 50000 @1 [INR]` |

`[INR]` marks `price_unit_id` = the INR unit. A line of INR priced in INR at
1 is "at par": it carries rupees and no euro figure.

**Why `cost` exists.** The spec requires that a remittance lot cost *exactly*
X euros. A per-unit price cannot give that: 1000 / 90000 does not terminate.
Stored at the column's 8 places it is `0.01111111`, and 90000 × that is
`999.9999`. Even in memory, `validate_lines` would compare
`999.99999999999999999999999999` against `1000` and refuse the entry. A stated
total is the only exact representation.

**Why `price_unit_id` exists.** A purchase paid in rupees has no euro figure
until the lots are replayed. It still has a figure, in rupees, and that
figure does two jobs:

- **The entry can balance at record time.** It balances in rupees, so a typo
  is still refused on the spot.
- **One payment can fund several lines.** The consumed euro cost is split
  among them in proportion to their rupee values (§3.3). A plain "lot-valued"
  flag could do neither: it would not say which currency pays which line.

### 2.2 Balancing per price currency (`validate_lines`)

The existing checks stay: at least two lines, and only leaves can be posted
to. The value check becomes one check per price currency. The new rules run
only when some line has a `cost` or a `price_unit_id`, so a base-currency
entry costs no extra query and fails exactly as today.

| Rule | Refusal |
|---|---|
| **V1.** Within each price currency (`NULL` is EUR), Σ debit face values = Σ credit face values. EUR is checked first. | `UnbalancedEntry(debits, credits, currency)`. With `currency=None` the message is exactly today's. Otherwise: `Entry does not balance in INR: debits … against credits …`. |
| **V2.** A price currency is a unit of kind `currency` other than the base. Checked where the name is resolved (`record --currency`, `record-split`'s sixth field), not in `validate_lines`. Those are its only writers, so a second check there would be for an impossible case. | `NotACurrencyUnit(identifier, kind)`, a `UnitError` |
| **V3.** A line of the price currency itself is at par: `unit_price` 1, no `cost`. | `CurrencyLineNotAtPar(identifier)` |
| **V4.** A line of a different currency unit is not priced in a non-base currency. A conversion between two non-EUR currencies is a non-goal. | `ConversionBetweenCurrencies(unit, currency)` |
| **V5.** A credit priced in a non-base currency is a line of that currency on an `asset` or `liability` account. | `CurrencyInflowWithoutRate(account, currency)`: `'Dividends' is credited in INR with no euro value; currency arriving needs a rate (record --rate)` |
| **V6.** A line with a `cost` or a `price_unit_id` has a quantity above 0. | `NonPositiveQuantity(quantity)` |

V3–V5 resolve unit kinds and account types through the account and unit
services. The lookup happens once per entry, and only when the rules run.

**What V5 buys.** It makes "an inflow without a rate" unrepresentable,
except as a move:

- An at-par rupee debit must, by V1, be balanced by at-par rupee credits.
- By V5, those credits come from asset or liability accounts. That means own
  accounts, which makes the entry a move, or People accounts, which the
  replay refuses (§3.4).
- A sale for rupees or a dividend in rupees therefore must carry a euro
  figure. That is the rate.

### 2.3 Euro values are derived at replay, never stored

The euro value of a line priced in a currency is the FIFO cost of the
currency it consumed. It is computed on every read by a full replay of the
currency lots in `(entry_date, line id)` order (§3). Nothing lot-derived is
written.

- **Order independence is structural.** A backdated entry changes nothing
  stored, so every reader sees exactly what a full replay computes. There is
  nothing to recompute and nothing to get stale. The spec's definition, "as a
  full replay in `(entry_date, line id)` order would compute it", is
  literally the implementation. Its testable form has a gap for same-date
  entries (§13.1).
- **Every future mutation stays consistent for free.** The `undo-delete-edit`
  brief proposes compensating entries. A materialised euro figure would make
  every mutation path re-derive it; a derived one cannot drift.
- **Recording never reads a lot or a price.** The recording path is unchanged
  in kind. `validate_lines` reads account types and unit kinds, never
  `prices` and never the replay. `tests/test_price_guards.py` holds.

### 2.4 The fold reads the same costs

`aggregate_by_unit` feeds `balance`, `net-worth`, `net-worth-history` and
who-owes-what. It gains a mapping from line id to euro cost:

```python
def aggregate_by_unit(lines: Iterable[JournalLine], costs: Mapping[int, Decimal] | None = None) -> list[UnitBalance]
def aggregate_by_unit_through(lines, dates, costs: Mapping[int, Decimal] | None = None) -> list[list[UnitBalance]]
```

`_RunningCost.apply(line, cost)`:

| Line | Basis change |
|---|---|
| In `costs`, debit | `+ cost` |
| In `costs`, credit | `− cost` |
| Not in `costs`, debit | `+ line.value`, which is today's `quantity * unit_price` for every existing row |
| Not in `costs`, credit | today's rule, moving average, with `line.value` as the net-short fallback in place of `quantity * unit_price` (identical for existing rows) |

**`costs` covers exactly two kinds of line** (§3.3):

- every line of a non-base currency unit;
- every line priced in one.

For a currency unit, therefore, every credit removes its FIFO cost, and the
fold's basis *is* the FIFO cost of what remains. Securities keep the moving
average, as `balance`'s `average cost` documents today.

**Why the fold may not stay moving-average for currencies.** Take the spec's
own example:

1. Remit 1,000 EUR for 90,000 INR.
2. Remit 1,100 EUR for 100,000 INR.
3. Buy shares for 120,000 INR.

The stock lot costs 1,330.00 (FIFO, spec). A moving-average fold would remove
2,100 × 120,000 / 190,000 = 1,326.32 from the rupees and leave 773.68. Net
worth at cost would then be 1,330.00 + 773.68 = 2,103.68 against 2,100.00
actually sent: a phantom 3.68 EUR gain on a purchase that "realises nothing".
With FIFO costs the rupees keep 770.00, and the total is 2,100.00 exactly.

**Who fetches `costs`, and when.** `journal.account_balance`,
`journal.net_worth_lines` (and with them `net_worth`, `NetWorth`,
`QueryAccountBalance`, `ValuedNetWorth`, `NetWorthHistory` and
who-owes-what), and `budgeting.QueryBudget` call `lots.line_costs(ctx,
lines)` on the lines they loaded.

- **It returns `{}` at once when none of those lines is lot-valued**, meaning
  a non-base currency or priced in one.
  - A ledger with no non-EUR currency unit therefore runs no replay, no extra
    query and no People lookup.
  - Nor does `balance` on a euro-only account in a ledger that does have
    rupees.
  - That is the spec's "balance and net-worth *wherever* their euro cost
    depends on lots", and it makes the no-regression goal structural rather
    than tested-for.
- **`NetWorthLines` gains `costs`**, computed once. `net_worth` and the
  history fold read the same mapping, so the final history row and
  `net-worth` stay one computation (PP §5.4).
- **The costs are of the whole ledger, and a line's cost does not depend on
  the query date.** It depends only on earlier lines. History can therefore
  use one mapping for every sample date.

### 2.5 Budget, and what `entries-in-period` shows

- **`budget`** sums expense lines through `net_spent`. It gains `costs` and
  uses `costs.get(line.id, line.value)`. An expense paid in rupees therefore
  counts at its lot cost, which is issue 114's "reports that show expenses".
- **`entries-in-period` lists face values, not lot-derived ones.** An at-par
  rupee expense shows `1500.00` with a new `priced in` column reading `INR`.
  - The column appears only when a listed line has a price currency, so
    existing output is unchanged.
  - `QueryJournalByPeriod` keeps its `list[JournalLine]` result, which tests
    pin. Showing the euro value instead would need a second listing use case.
  - This is a choice for the user (§13.9).

### 2.6 What the old readers of `unit_price` see

- `splitting.py` and `classification.py` copy `unit_price` into adjusting
  entries. They only ever reach imported entries: they need a classification
  record. Those are base-currency `CashRow` entries with no `cost` and no
  price currency, so the copy stays correct. `CashRow` stays base-only (spec
  Non-Goal).
- `held_units` folds without `costs`. It reads only quantities, so it is
  unaffected.

### 2.7 The import cycle, and where two names move

`journal.py` must now call `lots.line_costs`, and `lots.py` imports
`balance_sheet_accounts` from `journal.py`. Two moves break the cycle. Each
keeps every existing import path working through a re-export from
`journal.py`, written `from x import NAME as NAME` so ruff sees it as
intentional.

- **`PEOPLE_ROOT`, `BalanceSheetAccounts` and `balance_sheet_accounts` →
  `kohle/use_cases/accounts.py`.** That module is the domain noun for
  accounts and imports only services.
- **`BASE_CURRENCY` → `kohle/domain/models.py`.**
  - `lots.py` needs it to exclude the base currency.
  - The new model defaults `Price.currency` and `PriceBinding.quote_currency`
    need it too.
  - `domain` cannot import `use_cases`.
  - It is a ledger invariant ("cash in the base currency is stored at price
    1"), not a use-case detail.
  - PF §7's "no second copy" still holds: there is one definition,
    re-exported.

**Rejected: a function-level import inside `journal.py`.** It would hide the
cycle rather than remove it.

---

## 3. The replay (decision 2)

### 3.1 Filters

```python
def _foreign_currency(unit: Unit) -> bool:   # kind currency, identifier != BASE_CURRENCY
def _replayed(unit: Unit) -> bool:            # security, or _foreign_currency
```

- **Where kinds are named.** These two predicates are the only places the
  feature names a kind. No code names INR.
- **What a unit with no kind does.** Pure tests build `Unit(identifier="X1")`
  with no kind. Such a unit is not a foreign currency, so it takes the
  security path, as today.
- **The `lots_for` parameter.** `replay(lines, own, people=None,
  lots_for=_replayed)` takes it, and it decides which units get queues:
  - `replay_ledger` (`positions`, `realised`) passes `_replayed`;
  - `line_costs` (the fold, the budget) passes `_foreign_currency`.

  PP rejected a kind parameter for want of a second caller. The second caller
  now exists, with a forcing problem:
  - a security shortfall must not make `net-worth` fail, which today it does
    not;
  - security lots never influence currency costs, because a sale for rupees
    carries its own euro figure.

  So the fold readers replay currencies only.

### 3.2 Exact lot costs

`Lot.unit_cost` becomes a `fractions.Fraction`. Nothing else in `Lot`
changes:

```python
class Lot:
    acquired: date
    line_id: int
    quantity: Decimal
    unit_cost: Fraction        # exact; 1/90 for 1,000 EUR over 90,000 INR

    @property
    def cost(self) -> Fraction: ...    # Fraction(quantity) * unit_cost
```

- **Why exact.** A lot of 90,000 INR for 1,000 EUR has unit cost 1/90, which
  no `Decimal` holds. With `Fraction`, the lot's cost is exactly 1,000.
  Spending 30,000 of a 100,000 lot that cost 1,100 takes exactly 330.
- **Why keep `unit_cost` rather than store a total.** PP §4.2 made the split
  exact by keeping `unit_cost` per lot. That stays true, now for every lot.
- **Rejected: proportional splitting of a stored total.** That is
  `cost × part / quantity` with a remainder. It keeps the sum exact, but
  makes today's exact security splits inexact whenever the product exceeds
  28 digits.
- **Existing face-priced lots are unchanged in value.** Their unit cost is
  `Fraction(unit_price)`, which is exact for any `Decimal`. A face-priced lot
  therefore has the same exact cost it has today.
- **Figures leave the replay as `Decimal`.** `_decimal(f) =
  Decimal(f.numerator) / Decimal(f.denominator)` converts once, in the
  default context, for `Sale.fifo_cost`, `FifoHolding.fifo_cost` and every
  entry of `costs`.
  - Terminating values convert exactly: 1,330, 770, 600.
  - The existing exact assertions in `tests/test_lots.py` (1,600, 600, 350)
    hold.
- **Every `Lot` is built inside `lots.py`.** `_take` does no arithmetic on
  `unit_cost`, so `test_take_splits_a_lot_exactly`, which builds a `Lot` with
  a `Decimal` unit cost, passes unchanged.

### 3.3 One entry at a time

The replay groups lines **by entry**, in ledger order. Today it groups by
`(entry, unit)`. Within each entry it runs three steps.

**Step 1: each foreign currency C of the entry, in first-seen order** (only
when `lots_for(C)`).

| C-lines of the entry | Reading | Effect |
|---|---|---|
| Any line of C, or priced in C, on a People account | refused | `Err(CurrencyWithPeople)` (§3.4) |
| Own credits **and** own debits of C | a move | `_move`, unchanged: quantities must match (`UnbalancedOwnMove`), lots keep their dates and costs, and face figures are ignored. `costs[line]` is the cost moved out or dealt in. |
| An own debit of C with a euro figure | an acquisition | `Lot(date, line id, q, Fraction(face) / Fraction(q))`, where a face from `unit_price` gives `Fraction(unit_price)`. `costs[line] = face`. |
| An own credit of C with a euro figure | a disposal | FIFO from that account's queue. `Sale(proceeds = face, fifo_cost = consumed)`, so FX is realised: a reconversion, or rupees sold. `costs[line] = consumed`. |
| An own credit of C at par | a payment | FIFO from that account's queue. **No `Sale`.** `costs[line] = consumed`, and the consumed cost and quantity are added to the entry's `paid[C]` and `paid_qty[C]`. |
| A line of C on an income or expense account with a euro figure | face | `costs[line] = face` |

Acquisitions are processed before disposals and payments, as debits are
before credits today. An at-par own debit outside a move cannot occur: by V1
and V5 its only counterparts are at-par credits on asset or liability
accounts, and those are either own (a move) or People (refused).

**Step 2: the lines the payment bought.** These are the lines priced in C
other than own and People lines of C itself: a purchase debit, an at-par
expense line.

```
costs[line] = paid[C] × value_in_C(line) / paid_qty[C]
```

- **The division is exact** (`Fraction`), so the shares sum to `paid[C]`
  exactly.
- **The denominator is the quantity paid, not the sum of the loaded
  debits.** By V1 the two are equal. `replay_ledger` loads only own and
  People lines, so it does not see an at-par expense line, and the stock it
  does see still gets its own share and not the whole payment.
- **Worked example.** Pay 240,000 INR at par for 100 INFY at 1,200 INR and 60
  TCS at 2,000 INR. INFY gets half the consumed cost and TCS the other half.

**Step 3: other replayed units** (only when `lots_for(U)`). Everything here
is as today (PP §3.3): the People check, moves, purchases and sales.

- A purchase priced in C takes `costs[line]` from step 2 as its lot cost.
- Every other purchase takes its face value.
- A sale's proceeds are the line's face value. For a sale for rupees at a
  rate, that is the stated `cost`.

`LotReplay(sales, holdings, costs)`. `FifoHolding` gains `kind`, so
`positions` can tell a currency row (§8).

Against the spec's testable figures:

- **111:** the remittance lot costs exactly 1,000.00.
- **113:** the stock lot costs 1,000 + 1,100 × 30,000 / 100,000 = 1,330.00,
  and 70,000 INR remain at 770.00. The purchase emits no `Sale`.
- **115:** a reconversion of 70,000 INR for 800 EUR emits `Sale(INR, 70000,
  800, 770)`, a gain of 30. It is a `realised` row with unit `INR`.

### 3.4 Moves, shortfall and People, through the existing path

- **Moves.** `_move` and `_take` are reused unchanged. A move of rupees is an
  entry with own credits and own debits of INR, at par or at any equal euro
  price. The latter is how a user might write it with `record-split`, as
  for securities today.
- **Shortfall.** `LotShortfall` is reused. It names the unit, the account,
  the date and the shortfall, for a payment, a disposal or a move-out
  exceeding the account's rupee lots. Its hint "is an earlier purchase
  missing?" is kept, and `test_lots.py` pins its text.
  - A consequence: spending rupees from an account that holds no rupee lots,
    an INR credit card for instance, is a shortfall. Foreign-currency debts
    are outside this spec (§13.10).
- **People.** For a currency, any line of the currency or priced in it on a
  People account fails the replay with `CurrencyWithPeople(entry_id,
  entry_date, unit_identifier, people_account)`, whether or not an own line
  is present.
  - This is broader than the securities rule, which ignores People-only
    entries. Without it, an at-par rupee line between two people would be
    read by the who-owes-what fold as euros.
  - The spec's Non-Goal ("currency units to or from People accounts … are
    refused") covers it (§13.8).
  - Message: `Entry {id} on {date} puts {unit} on People account {person!r};
    currencies other than EUR cannot be owed by people`.
- **A new class, not `SecurityMoveWithPeople`.** `test_lots.py` pins that
  class's text, which says "securities". The same path raises the sibling.
- **Order.** Within an entry, the People check comes first, then the move
  balance, then shortfalls in line order. Currencies come before securities.
  The first failure in ledger order ends the replay, which is the spec's
  "fail as a whole".

### 3.5 The two loaders

```python
def replay_ledger(ctx) -> Result[LotReplay, RealisedError]
    # balance_sheet_accounts; account_lines_service(own | people);
    # lines where _replayed(unit) or price_unit_id is not None; replay(..., lots_for=_replayed)

def line_costs(ctx, lines: Iterable[JournalLine]) -> Result[dict[int, Decimal], BalanceError]
    # {} when no line in `lines` is lot-valued; else
    # balance_sheet_accounts; currency_lines_service(ctx, BASE_CURRENCY);
    # replay(loaded, own, people, lots_for=_foreign_currency).costs
```

**`currency_lines_service(ctx, base_identifier)`** is one query, in the
order `account_lines_service` uses. It returns the lines on every account
(income and expense included) that either:

- are of a unit of kind `currency` other than `base_identifier`; or
- have a `price_unit_id`.

It joined-loads `entry` and `unit`. The base identifier is passed in, so the
service names no currency.

- **The two replays agree on currency costs.** Both see the same own-account
  currency lines in the same order.
- **Why `line_costs` loads expense lines.** It loads all accounts because
  the budget needs the expense line's cost.
- **Why `replay_ledger` loads only own and People lines.** Its reports need
  only lots, and the denominator rule of §3.3 makes the partial load safe.

### 3.6 Errors

New `LotError` member, in `domain_errors.py`:

```python
LotError = LotShortfall | UnbalancedOwnMove | SecurityMoveWithPeople | CurrencyWithPeople
BalanceError = AccountError | JournalError | LotError
```

**`BalanceError` gains `LotError`.** `account_balance` and `net_worth_lines`
can now fail on lots. Every union built on `BalanceError` inherits it:
`ValuationError`, `HistoryError`, `RealisedError`, `PositionsError`,
`ListPriceTargetsError` and who-owes-what's. `BudgetError` gains it
explicitly. The CLI prints `str(err)` and exits 1 as for every other error.

---

## 4. Precision of the rate (decision 3)

**Decision: store the reciprocal as an ordinary price, at the column's 8
places.** `prices.price` stays `Numeric(20, 8)`. The `ecb` plugin returns
`(1 / quoted).quantize(Decimal("1E-8"))`, so what `fetch-prices` prints is
what is stored and read back.

**Measured in this venv** (SQLAlchemy 2.0.46, SQLite 3.45.1):

- SQLite stores the bound float with all its digits
  (`0.01040329409904352`).
- SQLAlchemy's `Numeric(20, 8)` reads it back formatted to 8 places
  (`Decimal('0.01040329')`).
- So the loss is the read's fixed scale, at most 5 × 10⁻⁹ EUR per unit.

| Currency (ECB, 2026-11-06) | Quoted | Stored reciprocal | Relative error |
|---|---|---|---|
| INR | 104.8645 (4 decimals) | 0.00953612 | ≤ 5.2 × 10⁻⁷ |
| JPY | 176.77 | 0.00565707 | ≤ 8.8 × 10⁻⁷ |
| IDR | 20208.93 | 0.00004948 | ≤ 1.0 × 10⁻⁴ |

Why this is negligible:

- **For INR the stored figure loses nothing the source had.** The ECB's own
  4-decimal quote on ~105 is uncertain by ±5 × 10⁻⁷ relative, the same order
  as the rounding.
- **In euros:**

  | INR held | Error |
  |---|---|
  | 10 lakh (1,000,000) | ≤ 0.005 EUR |
  | 1 crore (10,000,000) | ≤ 0.05 EUR |

- **The rate only ever feeds a market-value estimate.** Recording never reads
  it, so no cost, lot or realised gain depends on it. The estimate's
  inherent error dwarfs the rounding: a reference rate fixed at 14:10 CET
  against any rate the user could actually deal at, with a retail spread of
  about 0.5–1%. That holds even for IDR, the worst ECB currency, at about
  10⁻⁴.
- **Uniformity is preserved.** A rate stays "the price of the unit in EUR",
  so the INR row is valued by the same `quantity × price` rule as every
  other row (AGENTS.md: "reporting never branches on which kind it is").

Alternatives:

- **Rejected: store the rate as quoted (INR per EUR).**
  - It needs an inversion marker per binding or row.
  - Every reader would have to branch: `value_balances`, `positions`' price
    column, `fetch-prices`' previous-close detail.
  - A rupee row's "price" would mean the opposite of every other row's.
- **Deferred, the upgrade path: a price column type that reads back the
  stored float's shortest repr.** `Decimal(repr(value))` gives 16–17
  significant digits and returns typed closes exactly. About ten lines, a
  `TypeDecorator` over the same REAL storage, with no migration. It is not
  built, because no forcing problem exists for INR. Revisit if a
  high-unit-count currency (IDR, KRW) is ever held in amounts where 10⁻⁴
  matters.

---

## 5. Quote currencies, closes and rebinding (decision 4)

### 5.1 Per-row currency on `prices`; rebinding is never refused

| Table | New column |
|---|---|
| `price_bindings` | `quote_currency` `String NOT NULL DEFAULT 'EUR'`: the currency the symbol's closes are quoted in |
| `prices` | `currency` `String NOT NULL DEFAULT 'EUR'`: the currency this close is in, written with the row |

Both model columns carry `default=BASE_CURRENCY` as well as the server
default. Tests insert `Price(...)` rows directly, and after a server-side
default the attribute would expire, and a later read on a detached object
would fail.

**Why per-row and not refusal.**

- **A stored close describes itself.** Valuation reads the rate from the
  close's own `currency` (§8.1), so `value_balances` never needs the binding
  to interpret a price, and rebinding cannot reinterpret history.
- **Refusal is a dead end.** No command deletes prices: `fetch-prices` is
  the only writer. A user who bound an Indian symbol to `alphavantage`
  before this feature (the spec's Overview: binding an INR-quoted symbol
  today "would store a rupee price as euros") already has wrong rows
  labelled EUR. Under
  refusal they could never rebind that unit to `nse` in INR. Under per-row
  currency they rebind, the next fetch stores INR closes, and the latest
  close is right.
  - The old rows stay wrong for past dates in `net-worth-history`. Removing
    them needs a price-deletion command, which is outside this spec.
- **The transitional state is covered by the spec's own rule.** Between a
  rebind and the next fetch, the latest close is in the old currency. The
  per-currency subtotal then has "no close in that currency" and shows `-`.

Rebinding goes through the existing upsert. `set_price_binding_service`
compares and updates `quote_currency` with the plugin and symbol. An
identical rebind still writes nothing.

### 5.2 `set-price-source` and `validate_close`

`SetPriceSource.execute(identifier, plugin_name, symbol, available_plugins,
quote_currency=BASE_CURRENCY)`. The existing checks keep their order, then:

| Unit | Rule | Refusal |
|---|---|---|
| security | quote currency is EUR or an existing unit of kind `currency` | `NotAQuoteCurrency(code)` |
| currency other than EUR | quote currency is EUR: a rate is a price in euros | `RateNotQuotedInEur(unit, code)` |
| EUR, commodity | unchanged: `NotASecurityUnit` | (§13.6) |

`validate_close(close, today, quote_currency=BASE_CURRENCY)` keeps its order:
price, then date, then currency.

- **On a mismatch it returns `NonBaseCurrency(close.currency,
  quote_currency)`.**
- **The class name is kept because tests pin it.**
  `test_validate_close.py` and `test_append_prices.py` assert `isinstance(…,
  NonBaseCurrency)` and `.base == "EUR"`. The docstring now says `base` is
  the binding's quote currency.
- **The message becomes** `Close is in 'USD', but its binding quotes in
  EUR`. No test or docs example asserts the old text.

`AppendPrices` validates **per unit**, with that unit's quote currency,
because two units bound to one symbol may differ. It writes
`currency=close.currency` with the row.

### 5.3 The plugin contract: `fetch_bound_closes`

```python
class PriceFetcherPlugin(ABC):
    def fetch_bound_closes(
        self, symbols: Sequence[str], quote_currencies: Mapping[str, str]
    ) -> Result[dict[str, PriceResult], PriceFetchError]:
        """What core calls. `quote_currencies[symbol]` is the currency the binding names.
        A plugin that knows its data's currency ignores it and reports the truth;
        core checks that against the binding."""
        return self.fetch_latest_closes(symbols)
```

- **`call_price_plugins` calls `fetch_bound_closes`.** `alphavantage`
  overrides it and stamps `currency=quote_currencies[symbol]`. That is the
  spec's "reports the binding's quote currency", the binding being the
  user's assertion. Its `fetch_latest_closes(symbols)` becomes
  `fetch_bound_closes(symbols, dict.fromkeys(symbols, "EUR"))`, which is
  today's behaviour.
- **Why a concrete method and not a second parameter.** Existing tests pin
  the one-argument call:
  - `ThirdPricePlugin` in `test_price_guards.py` and the plugin in
    `test_docs_plugin_list.py` define `fetch_latest_closes(self, symbols)`
    only;
  - `test_alphavantage_plugin.py` calls it and expects `currency="EUR"`.

  The default delegation keeps all three working, and keeps third-party
  plugins unbroken. That is PF's "adding with a default is compatible",
  applied to a method.
- **Rejected:**
  - **`Close.currency: str | None`, with `None` meaning "as bound".** It
    breaks the alphavantage test. It also lets any plugin opt out of the
    check by omission, which undoes PF §2.2's "a plugin states the currency
    every time".
  - **A class flag such as `currency_from_binding = True`.** The plugin's
    `"EUR"` literal would then be a lie that core ignores.
- **Two units on one symbol with different quote currencies.** The mapping
  passed to the plugin takes the currency of the first unit by identifier.
  The other unit's close is refused by its own per-unit check, so the
  conflict is loud on every fetch. Nothing refuses such a binding, as PF
  §14.6 left same-symbol bindings open.
- **`PriceTargets` gains `quote_currencies: dict[int, str]`** (unit id to
  binding currency), filled by `ListPriceTargets`.

### 5.4 What `fetch-prices` fetches

`ListPriceTargets` selects held securities as today, plus held foreign
currency units (`held_units` already folds every unit). It also adds **the
quote currency of every held bound security**, held or not.

**Why the quote currencies too.** If every rupee has been spent on shares,
INR's net quantity is 0. Without the extra targets the INR rate would never
be fetched, and every Indian stock would be valued at cost (§13.3).

Output and messages:

- **An unbound target currency shows as `unbound`,** which prompts the user
  to bind INR to `ecb`.
- **`No held securities` and `N held securities unpriced` keep their
  wording.** For a ledger with no non-EUR currency unit the output must not
  change (§13.14).
- **The `close` cell appends the currency when it is not EUR**
  (`1181.40 INR`). The `previous …` detail does the same.

### 5.5 The `file` plugin

The header may be `identifier,date,close` (as today) or
`identifier,date,close,currency`.

- A missing column, or an empty cell, means EUR.
- Any other header is still `MalformedPriceFile`.
- The plugin reports each row's currency literally, so a misquoted file row
  is refused by core per unit, not guessed.

---

## 6. CLI flags (decision 5)

### 6.1 `record`

Three new options. Existing options and their messages are unchanged.

| Option | Meaning |
|---|---|
| `--total T` | The entry's value as a whole, instead of QUANTITY × price. Needs `--from-unit` or `--to-unit`, and excludes `--from-price` and `--to-price`. It is in EUR, or in `--currency`. |
| `--currency C` | The side without a unit flag carries currency C at par instead of euros, and any price or total is in C. C must be a currency unit other than EUR. |
| `--rate R` | Euros per unit of C, for C *arriving*. C's line, and the other line, carry the euro value C-amount × R. Needs `--currency`. |

**Refused before any session, with `click.BadParameter`, exit 2:**

- `--total` without a unit flag;
- `--total` together with a price;
- `--rate` without `--currency`;
- `--rate` with `--to-unit`, because a purchase takes its cost from the lots
  and a rate there would silently realise FX;
- `--currency EUR`, because it is the default;
- `--currency` naming the unit flag's unit;
- a QUANTITY that is not above 0 with `--total` or `--currency`.

**The new forms**, where Q is QUANTITY:

| Command | Lines |
|---|---|
| `record D "Remittance" 90000 --from Girokonto --to IndianBank --to-unit INR --total 1000` | `Girokonto cr EUR 1000` · `IndianBank dr INR 90000 cost=1000` |
| `record D "Opening" 100 --from Opening --to Demat --to-unit INFY --total 1500` | the same form, with a security (112) |
| `record D "Back to euros" 70000 --from IndianBank --to Girokonto --from-unit INR --total 800` | `IndianBank cr INR 70000 cost=800` · `Girokonto dr EUR 800` (115) |
| `record D "Buy INFY" 100 --from DematCash --to Demat --to-unit INFY --to-price 1200 --currency INR` | `Demat dr INFY 100 @1200 cost=120000 [INR]` · `DematCash cr INR 120000 @1 [INR]` (113) |
| `record D "Groceries" 1500 --from IndianBank --to Groceries --currency INR` | both lines INR at par (114) |
| `record D "To demat" 50000 --from IndianBank --to DematCash --currency INR` | the same shape, which the replay reads as a move (117) |
| `record D "Sell INFY" 50 --from Demat --to DematCash --from-unit INFY --from-price 1300 --currency INR --rate 0.0104` | `Demat cr INFY 50 cost=676` · `DematCash dr INR 65000 @0.0104 cost=676` (116) |
| `record D "Dividend" 2000 --from Dividends --to DematCash --currency INR --rate 0.0104` | `Dividends cr INR 2000 @0.0104 cost=20.80` · `DematCash dr INR 2000 @0.0104 cost=20.80` (116) |

- **`Total` and `CurrencySide` are value objects.** `CrossUnitLine.price`
  becomes `Decimal | Total`, and
  `RecordSimpleEntry.execute(..., cross=None, currency_side: CurrencySide |
  None = None)` takes the side. These are the house's answer to mutually
  dependent inputs (`CrossUnitLine`'s docstring): a rate without a currency
  cannot be built, and existing positional calls are unchanged.
- **Computed products are quantised to the column's 8 places before
  validation.** That covers quantity × price in a currency, and amount × rate.
  They are then stored as `cost` on the holding line and as the cash line's
  quantity, so what is validated is what is stored.
- **The existing EUR `--to-price` path is left alone,** including its
  unquantised product. Changing it is outside the no-regression envelope
  (§13.17).
- **Opening entries** (112) are the remittance form with `--from` an account
  the user names. The docs recommend `--type income`, so the opening
  increases net worth.
- **`record` names its new results:**
  - `Recorded 90000 INR for 1000 EUR: credited …, debited …`;
  - `Recorded 1500 INR: …`;
  - `Recorded 2000 INR at 0.0104 EUR: …`.

  The implementer settles exact wording with the docs page.
- **"Usage error" for a rate-less inflow (spec, 116).**
  - A sale for a currency without `--rate` is caught before the session,
    exit 2.
  - A dividend without `--rate` cannot be told from a move until the
    accounts are read. `validate_lines`' V5 refuses it with
    `CurrencyInflowWithoutRate`, whose message names `--rate`, and the
    command exits 1 like every domain refusal (§13.4).

### 6.2 `record-split`

The line stays `ACCOUNT:QUANTITY:UNIT:PRICE:SIDE`. Two extensions:

- **PRICE may be `=T`,** a total.
- **An optional sixth field names the price currency,** default EUR.

```
--line Girokonto:1000:EUR:1:credit --line IndianBank:90000:INR:=1000:debit      # remittance
--line DematCash:120000:INR:1:credit:INR --line Demat:100:INFY:1200:debit:INR    # purchase in INR
--line IndianBank:1500:INR:1:credit:INR --line Groceries:1500:INR:1:debit:INR    # expense in INR
--line Demat:50:INFY:=676:credit --line DematCash:65000:INR:0.0104:debit         # sale at a rate
```

- **A rated inflow needs no new syntax.** It is the rupee line at a euro
  unit price, which is the existing grammar.
- **`LineInput` gains `price_currency: str | None = None`**, and `unit_price`
  becomes `Decimal | Total`. Existing constructions, including
  `test_line_parser.py`'s equality, are unchanged.
- **`RecordSplitEntry` resolves the price currency strictly**, as it does
  units: `EUR` maps to `NULL`, and a non-currency unit is `NotACurrencyUnit`
  (V2).

Every form of 111–116 is thus expressible (119). Two differences from
`record` are allowed:

- **The rated rupee line may carry no `cost`.** It is valued as quantity ×
  rate, whereas `record` always stores `cost`.
- **The display `unit_price` may differ** when a rate has more than 8
  decimals.

Reports read face values and lots, so the results are identical.

### 6.3 `set-price-source`

`set-price-source UNIT PLUGIN SYMBOL [--currency CODE]`, defaulting to EUR.

- The output appends ` (CODE)` only when it is not EUR:
  `Price source for INFY: nse INE009A01021 (INR)`.
- Existing output and the docs example are unchanged.

**Rejected: `--eur X` for the two-amount form.** It names the base currency
in a flag and cannot state a rupee total, such as a purchase with fees
(`--to-unit INFY --total 120450 --currency INR`). `--total` is the per-line
twin of `--to-price` and covers both. Also rejected:

- **separate `--from-total` and `--to-total`.** The side is already given by
  the unit flag;
- **a `record-fx` command.** It would be a parallel command for one more
  form;
- **ledger-cli's `@@`.** `=` is shell-safe and reads as "equals in total".

---

## 7. ECB and NSE (decision 6)

### 7.1 What was verified, on 2026-11-07, from this machine

**ECB.**

- **Endpoint.** `https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml`
  returned 200 `text/xml`, 1.5 KB.
  - Its structure is `<Cube time='2026-11-06'>` containing `<Cube
    currency='INR' rate='104.8645'/>` and 29 other currencies, all quoted per
    1 EUR, under the namespace
    `http://www.ecb.int/vocabulary/2002-08-01/eurofxref`.
  - `Last-Modified: Fri, 06 Nov 2026 14:56:34 GMT`, which is 15:56 CET.
- **Publication** (ECB reference-rate page, quoted):
  - "The reference rates are usually updated at around 16:00 CET every
    working day, except on TARGET closing days."
  - "They are based on the daily concertation procedure … around 14:10 CET."
  - "The reference rates are published for information purposes only. Using
    the rates for transaction purposes is strongly discouraged."
- **Finality.** The daily file carries **no status or revision marker**.
  - It holds one dated cube, the latest published working day, and changes
    once a day on publication. There is no provisional intraday rate.
  - The SDMX series (`data-api.ecb.europa.eu/service/data/EXR/D.INR.EUR.SP00.A`)
    marks the same observations `OBS_STATUS=A` (normal), `OBS_CONF=F`
    (free), `DECIMALS=4`, titled "… 2.15 pm (C.E.T.)". That adds nothing for
    finality.
  - **Decision: a rate dated D in the daily file is final.**
  - **Not verified:** whether the ECB ever revises a published reference
    rate. The reuse policy says statistics "may be changed as a result of
    revisions". `prices` is append-only, so a revision is never picked up
    (PF §14.8's "already stored").
- **Terms.** The ESCB statistics reuse policy, quoted: "All publicly
  available ESCB statistics may be reused free of charge on the condition
  that the source is quoted (e.g. 'Source: ECB statistics.') and that the
  statistics (including metadata) are not modified." The ECB disclaims all
  liability for use of the rates. What this means for kohle:
  - **Valuation is information use**, which is the stated purpose.
  - **kohle stores a derived figure (the reciprocal) in a private ledger**
    and republishes nothing.
  - **`prices.md` credits "Source: ECB statistics"** where it describes the
    plugin.
  - **The docs say the stored figure is the reciprocal,** so it is not
    passed off as the ECB's number.
  - **The spec's "typically the user looks up the ECB rate"** for an inflow
    uses the rate for bookkeeping, not to deal at. The docs say the rate
    entered is the user's choice.

**NSE.**

- **Endpoint.**
  `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`.
  - With a browser `User-Agent` and `Referer: https://www.nseindia.com/`,
    2026-11-06 returned 200 `application/zip` (208 KB, one member
    `BhavCopy_NSE_CM_0_0_0_20261106_F_0000.csv`, 3,715 rows).
  - The Saturday 2026-11-07 returned **404 with an HTML body**.
  - Without the headers the request failed with `HTTP/2 stream … INTERNAL_ERROR`,
    as the brief recorded.
- **Columns** (34): `TradDt, BizDt, Sgmt, Src, FinInstrmTp, FinInstrmId,
  ISIN, TckrSymb, SctySrs, …, ClsPric, LastPric, PrvsClsgPric, …`.
  - `INE009A01021` `EQ`: `ClsPric 1181.40`, `TradDt 2026-11-06`.
  - No ISIN had two `EQ` rows. `EQ` covered 2,746 rows, then `SM` 384,
    `BE` 201 and others.
- **Terms: not verified.** I could not locate NSE's terms on automated
  download:
  - `/terms-of-use` and similar paths return 404;
  - a further probe was refused by this session's permission policy.
  - `www.nseindia.com/robots.txt` allows `/` except `/market-data-test`, and
    the archive host has no `robots.txt`. **That is not a licence.**
  - The user accepted bhavcopy as a source (spec). The risk stays theirs, and
    `prices.md` says the terms are unverified.

### 7.2 `ecb` (109)

`EcbPriceFetcher`, name `ecb`, entry point `ecb`, in
`kohle/app/plugins/kohle_ecb_price_fetcher.py`. It copies alphavantage's
shape. Its seam is `http_get: Callable[[str], bytes] = _urlopen_get`, and
tests replace it with a recorded `eurofxref-daily.xml` fixture.

1. **One GET of the daily file per run, whatever the number of symbols.**
   `OSError` → `Err(EcbUnreachable)`.
2. **Parse with `xml.etree.ElementTree`.**
   - Anything but exactly one dated cube → `Err(UnexpectedEcbResponse)`.
   - So is an unparseable `time` or `rate`, or a rate ≤ 0. Never a guess.
   - stdlib's bundled expat 2.6.1 (checked in this venv) has had
     billion-laughs protection since 2.4. The source is one fixed host over
     TLS, so `defusedxml` is not added.
3. **For each requested code:**
   - found → `Close(price_date=time, price=(1 / rate).quantize(1E-8),
     currency="EUR")`;
   - absent → `Unavailable(no_symbol, "the ECB publishes no reference rate for
     XYZ")`.

No key, no environment variable, no state. The `"EUR"` is a literal, for
PF §9.2's reason.

**Rejected: the SDMX API.** It is one request per currency, and its status
attribute adds nothing (§7.1).

### 7.3 `nse` (110)

`NsePriceFetcher`, name `nse`, entry point `nse`, in
`kohle/app/plugins/kohle_nse_price_fetcher.py`.

- **Seams.** `http_get: Callable[[str, Mapping[str, str]], bytes]` raises
  `urllib.error.HTTPError` for a 404. `today: Callable[[], date] =
  date.today`. Tests replace both.
- **Headers:** a browser `User-Agent`, `Referer: https://www.nseindia.com/`
  and `Accept: */*`.

1. **Find the file.** Start at `today()` if it is a weekday, else the last
   weekday before it.
   - On a 404, step back one weekday, for at most 10 weekdays.
   - If none is found → `Err(NoBhavcopyFound(first, last))`. That keeps a URL
     change by NSE loud rather than an endless walk.
   - Any other `HTTPError` or `OSError` → `Err(NseUnreachable)`.
   - Today's file may not exist yet, because it is published after the
     close. The 404 then just steps back, so no strictly-before-today guard
     is needed: a published bhavcopy is a finished close (brief).
2. **Read the file.** The zip must hold exactly one CSV member. It is read
   with `csv.DictReader`, and the header must contain `TradDt`, `ISIN`,
   `SctySrs` and `ClsPric`. Otherwise `Err(UnexpectedBhavcopy("…"))`, never
   a guess.
3. **For each requested ISIN, take the rows with `SctySrs == "EQ"`:**
   - none → `Unavailable(no_symbol, "no EQ row for <ISIN> in the bhavcopy of
     <date>")`;
   - more than one → `Err(UnexpectedBhavcopy)`;
   - an unparseable `ClsPric` or `TradDt`, or a `TradDt` that is not the
     file's date → `Err(UnexpectedBhavcopy)`;
   - else `Close(price_date=TradDt, price=ClsPric, currency="INR")`.

**Fixtures:**

- a zip trimmed from the recorded 2026-11-06 file, keeping its real header
  and a handful of rows (an `EQ` row, a `BE`-only ISIN, an `SM` row);
- a zip whose header lacks `ClsPric`;
- a 404 sequence across a weekend and a holiday.

**A consequence of matching `EQ` only, as the spec decided.** A stock moved
to the `BE` (trade-for-trade) series becomes `no_symbol`. The detail text
says so (§13.15).

**Rejected: `nselib`, `jugaad-data` and `nsepy`.** They are unofficial
scrapers with pandas-heavy dependency sets (`nsepy` is unmaintained), for a
job that is one zip of CSV.

---

## 8. Valuation and reports

### 8.1 A close and its rate, read in one place

```python
def _quote(ctx, unit_id, as_of, max_age_days, rates: dict[str, LatestClose]) -> Result[tuple[LatestClose, LatestClose | None], PriceError]
```

- **What it reads.** It calls `latest_close` for the unit. If that is
  `Fresh` or `Stale` and its `currency` is not EUR, it also reads the rate:
  `latest_close` of the unit whose identifier is that currency, with the
  same `as_of`.
- **The rate is read once per currency per call.** `rates` is a local
  `dict` owned by one `value_balances` or `QueryPositions` call. So every
  row of one report uses the same rate row. That is consistency, not
  caching for speed. PP §5.5 rejected preloading every close for in-memory
  search, which is a second read path. This dict only holds rates already
  read through `latest_close`, within one call.
- **A missing currency unit is impossible**, because bindings validate it
  and units are never deleted. The `UnitError` is mapped to `PriceError` and
  not handled further.
- **`value_balances` stays "the only place the lookup condition is
  written".** `QueryPositions` calls `_quote` too, so `latest_close` stays
  the only function that reads a price row (issue 120).

Valued rows gain `rate: LatestClose | None = None`. The default keeps
`ValuedBalance(b, close)` in `test_valuation.py` working.

| Function | Rule |
|---|---|
| `_market_value(quantity, close, at_cost, rate=None)` | `Fresh`/`Stale` close and rate `None` → quantity × close; `Fresh`/`Stale` close and rate `Fresh`/`Stale` → quantity × close × rate; any `NoClose` → `at_cost`; close `None` → quantity |
| `valuation_status(close, rate) -> LatestClose \| None` | rate `None` → close; either `NoClose` → `NoClose()`; either `Stale` → `Stale(the older of the two Price rows)`; else `Fresh(close)` |

- **`summarise` counts by `valuation_status`.** `_market_columns` takes its
  `status` cell from it, and `price` and `price date` from the close itself.
- **That gives the spec's rules:**
  - the worse of the two;
  - a stale status that shows the older date;
  - `no price (at cost)` when either is missing.
- **Rupee cash is the degenerate case.** Its close is the INR rate in EUR,
  with no rate behind it, so it is valued at quantity × rate under the same
  code.
- **`net-worth-history` needs nothing new (123).** It already values each
  date through `value_balances(as_of=D)`.

### 8.2 Rendering, with no change for EUR-only tables

- **`quoted in` column.** It appears after `price` in `balance`,
  `net-worth` and `positions` only when some row's close is not in EUR, and
  holds that close's currency. That is the spec's "price … labelled with it"
  (121).
- **Rates get 8 decimals.** `.2f` would print a rate as `0.01`. When a table
  has a row of a foreign currency unit (`UnitBalance.kind` /
  `FifoHolding.kind`, §3.3), the per-unit columns (`price`, and `balance`'s
  `average cost`) are rendered as pre-formatted, right-aligned strings:
  - 8 decimals for currency rows;
  - 2 for the rest.

  Otherwise they stay `Decimal`s under `floatfmt=".2f"` exactly as today.
  Pre-formatting the whole column respects MV §6.4's trap: one string makes
  tabulate treat the column as text.

`UnitBalance` gains `kind: UnitKind | None = None`, filled by the fold from
`line.unit.kind`. It is positional-compatible with `test_valuation.py`.

### 8.3 Per-currency subtotals (122)

```python
@dataclass(frozen=True, slots=True)
class Subtotal:
    currency: str
    native: Decimal | None     # None prints "-"
    euro: Decimal

def holding_currencies(ctx, unit_ids) -> Result[dict[int, str], PriceError]
    # kind currency → the unit itself; bound → binding.quote_currency; else EUR
def subtotals(rows: Iterable[ValuedRow], currencies: Mapping[int, str]) -> list[Subtotal]
```

- **`native`** sums each member's market value in the subtotal's currency:
  - the row is the currency itself → its quantity;
  - a zero quantity → 0;
  - a close in that currency → quantity × close;
  - else `None`, and the whole subtotal's `native` is `None`.
- **`euro`** sums `market_value`, so the euro total is unchanged and still
  equals the sum of the rows.
- **`[]` when every row's currency is EUR.** Then nothing prints, which is
  the no-regression goal (§13.7).
- **The order** is EUR first, then by code.
- **`net-worth`** computes it over own and receivable rows in
  `ValuedNetWorth` and stores it in a new field,
  `ValuedNetWorthReport.subtotals: list[Subtotal]` (default `[]`).
  `net-worth-history`'s rows keep `[]`, because the spec gives history no
  subtotals.
- **`positions`**: `QueryPositions` returns
  `PositionsReport(positions, subtotals)`.
  - PP §8.3 rejected a wrapper for want of a forcing problem. Subtotals need
    the bindings, which only the use case can read.
  - No test calls `QueryPositions` directly.
- **Output.** After the existing closing lines, a blank line and a small
  table: `currency`, `market value`, `in EUR`.
- **`balance` and `net-worth-history` get none**, per the spec. The user is
  asked to confirm in its Open Question.

---

## 9. Migration plan off the current head (decision 7)

The head is `d7f3b9a1c846` (`rerun_rule_on_classifications`). There is one
migration per schema-bearing slice, the chain stays linear, and each
downgrade refuses what the older schema cannot represent. That is the house
refusal standard (PF §4.2, expense-splitting §10.3).

| Slice | Migration | Upgrade | Downgrade |
|---|---|---|---|
| 107 | `<a>_quote_currencies.py`, down `d7f3b9a1c846` | `price_bindings.quote_currency` and `prices.currency`, `String NOT NULL server_default 'EUR'`, plain `op.add_column` | refuse when any binding or price is not `'EUR'`; else batch-drop both. After a downgrade a rupee close would read as euros, which is the bug the spec opens with. |
| 111 | `<b>_journal_line_cost.py`, down `<a>` | `journal_lines.cost Numeric(20, 8) NULL`, plain `op.add_column` | refuse when any `cost` is not `NULL`; else batch-drop |
| 113 | `<c>_journal_line_price_unit.py`, down `<b>` | `batch_alter_table("journal_lines")` adds `price_unit_id INTEGER NULL` with `ForeignKey("units.id", name="fk_journal_lines_price_unit_id_units")` | refuse when any is not `NULL`; else batch-drop |

**Verified in this venv** (Alembic 1.18.3, SQLite 3.45.1):

- **A plain `op.add_column` carrying a `ForeignKey` fails** with
  `NotImplementedError`, after the column itself was already added. So C
  must use batch mode.
- **A plain `add_column` with a constant `server_default` works** and fills
  existing rows. So A and B need no table rebuild.

Notes:

- **`HEAD_REVISION`** in `kohle/db/schema.py` follows each slice.
  `test_head_revision_is_pinned_to_alembics_head` checks it.
- **`tests/test_migration_downgrade.py` gains per-migration cases,** in its
  existing style: round-trip when empty or all-EUR, and refusal with one
  offending row. The existing downgrade tests insert rows by raw SQL; the
  server defaults fill the new columns, so they pass through these
  downgrades unchanged.
- **The model changes land in the same slice as their migration**, so
  `create_all` and Alembic agree at every commit.
- **`JournalLine.unit` gains `foreign_keys=[unit_id]` in slice 113.** A
  second foreign key to `units` would otherwise make the relationship
  ambiguous.
- **If the order in §12 changes**, whichever schema slice lands later takes
  the earlier one's revision as `down_revision`.
- **The live ledger in the repository** (`kohle.db`, checked read-only) is
  at `d4e7a8c15b92`. It has one currency unit, EUR, plus 2 prices and 2
  bindings. `migrate` brings it to head, where the defaults make every row
  read as today.

---

## 10. Decimal handling

MV §7 holds:

- the default context;
- nothing quantised in reports;
- `.2f` cells;
- totals that equal the sums of the unrounded rows.

What changes:

- **Lot arithmetic is exact** (`Fraction`). It is converted to `Decimal`
  once per reported figure. A non-terminating cost (1,000 / 3) prints its
  28-digit rounding at `.2f`, and nothing compares it exactly.
- **`UnitBalance.average_cost` is `basis / quantity`, as today.** For a
  currency lot with a non-terminating unit cost, `at_cost` is therefore
  within 10⁻²⁵ of the FIFO cost. The printed figures agree.
- **Values computed at record time are quantised to 8 places before
  validation** (§6.1): quantity × price in a currency, and amount × rate.
  Typed values are stored as given, and SQLite rounds both lines alike.
- **A rate's relative error is bounded in §4.**

---

## 11. The decision categories

### State and data lifecycle

- **An entry is still one transaction.** `validate_lines` and the insert
  run in one `UnitOfWork`, so a refusal writes nothing.
- **Nothing lot-derived is stored, so there is no derived state to keep
  consistent.** Backdated entries, future deletes, edits and compensations
  need no recomputation. This is the spec's order-independence by
  construction (§2.3).
- **A close and its currency are written in one row.** `prices` stays
  append-only, and a rebind cannot reinterpret history (§5.1).
- **A binding's quote currency changes through `crud_update`**, so it is in
  the audit trail. As before, the `Operation` records that an update
  happened, not the old value.
- **Reports are pure reads.** A lot error fails the whole report before
  anything is printed. A missing close or rate is a value (`NoClose`) with a
  fallback, not a failure.
- **Migrations are reversible** where the older schema can hold the data,
  and refuse otherwise (§9).
- **Replayable.** The same database, flags and `today` give the same
  output. Lots are rebuilt on every run.

### Error propagation

```
validate_lines   JournalError subclasses (V1, V3–V6)         → RecordEntryError, unchanged union
name resolution  NotACurrencyUnit (V2), a UnitError          → RecordEntryError, unchanged union
replay           LotError, now with CurrencyWithPeople       → BalanceError ∋ LotError
journal folds    BalanceError                                → balance, net-worth, history, who-owes-what
budgeting        BudgetError ∋ LotError
prices           SetPriceSourceError ∋ NotAQuoteCurrency, RateNotQuotedInEur (PriceError)
AppendPrices     NonBaseCurrency per unit, as a value         → Unpriced outcome, never a rollback
plugins          PriceFetchError subclasses per plugin        → Unpriced for that plugin's units
reporting        UnitError for a quote currency's unit        → mapped to PriceError (impossible case)
CLI              str(err), exit 1; flag-shape errors exit 2 before any session
```

Representation changes in exactly these places:

- `validate_lines` turns line facts into named refusals;
- the replay turns queue state into `LotError`;
- plugins turn I/O into their own `PriceFetchError`s;
- the CLI turns any `Err` into its text.

**`lots.py` knows accounts only through the partition maps it is handed.**
It knows prices not at all.

### Concurrency and ownership

**Single-threaded, with no shared mutable state.**

- The CLI creates one session per command.
- Replay queues, `paid` totals and the `rates` dict are local to one call.
- Everything returned is frozen dataclasses.
- Plugins are called outside any transaction, as before. `ecb` makes one
  request per run; `nse` makes one, plus at most 10 404-probes.
- A concurrent `fetch-prices` can be seen part-way through a report. That is
  harmless, for MV §5's reason.

### Reuse

**Used rather than rebuilt:**

- `_move`, `_take`, `bisect.insort`, `LotShortfall`, `UnbalancedOwnMove`;
- `balance_sheet_accounts` and `account_lines_service`'s ordering;
- `latest_close` (the rate is a close), `value_balances`, `_market_value`,
  `summarise`, `_market_columns`, `_estimates_line` and `MAX_AGE_DAYS`;
- the set-price-source upsert;
- alphavantage's injected-HTTP seam and response-classification style;
- `UnavailableReason`;
- the migration refusal pattern;
- `test_pre_feature_equivalence.py`'s captured-oracle pattern (124);
- `_patched_entry_points` and `people_root` in tests.

**Worth reusing next:**

- **`fetch_bound_closes`**, for any source that cannot tell its currency;
- **`line_costs` and `currency_lines_service`**, for any future report that
  needs euro values of lines paid in a currency;
- **the bhavcopy reader**, if BSE is ever added. Only the URL and the series
  filter differ;
- **`valuation_status`**, if a third factor ever joins a valuation.

### Extension points

| Extension | Seam | Contract |
|---|---|---|
| A plugin that cannot tell its data's currency | `PriceFetcherPlugin.fetch_bound_closes` | It receives the binding's currency per symbol and returns closes keyed as requested. The default delegates to `fetch_latest_closes`. |
| Indian bank and demat importers (follow-up briefs) | `LineSpec(price_unit_id=…)`, at-par lines | The line shape for "paid in INR" exists. `CashRow` stays base-only until those briefs decide its currency field. |
| Another currency | none needed | No code names INR. Bind it to `ecb` and record with `--currency`. |
| Commodities in lots | `_replayed` | As PP §8.4 |
| Exact price storage | the `prices.price` column type | §4's deferred `TypeDecorator`, with no migration |
| Rate chains, currency-to-currency conversion | **none** | V4 refuses conversions, and `_quote` reads one rate level. Both are Non-Goals. |
| Euro values in `entries-in-period` | a listing use case over `line_costs` | §13.9 |

### Build vs. buy

| Component | Decision | Evaluated, and why not |
|---|---|---|
| Multi-currency lots and cost | **build**, extending `lots.py` | **beancount** books FIFO with `{}` cost and `@@` totals, but over its own ledger model: the whole ledger would be exported, and the own/People partition re-expressed (PP's reason). **py-moneyed** gives money types, not lots. |
| Exact rational arithmetic | **buy**: stdlib `fractions` | `Decimal` cannot hold 1/90 (§3.2) |
| ECB client | **build** (~60 lines) | **CurrencyConverter** (PyPI) ships and fetches the ECB history zip, but brings its own date-fallback and interpolation rules and a data file, for a 1.5 KB XML parse. **forex-python** depends on third-party rate APIs. **sdmx1** is a full SDMX stack. |
| NSE client | **build** (~90 lines) | §7.3: unofficial, heavy or unmaintained |
| XML parsing | stdlib `ElementTree` | `defusedxml` is not a dependency. Expat 2.6.1 already mitigates entity expansion, for a single trusted host. |
| HTTP | stdlib `urllib.request` | as PF |
| Exact price storage | **not built** | §4 |

### Abstractions introduced

| Abstraction | Forcing problem |
|---|---|
| `JournalLine.cost` / `LineSpec.cost` | A two-amount lot must cost exactly X, and X / Y does not terminate (§2.1). |
| `JournalLine.price_unit_id` / `LineSpec.price_unit_id`, `JournalLine.price_unit` | A line with no euro face must still balance, and say which currency paid it; `entries-in-period` names it (§2.1, §2.5). |
| `Total` | A per-unit price and a total are mutually exclusive inputs (§6.1). |
| `CurrencySide` | A rate is meaningless without its currency (§6.1). |
| `Lot.unit_cost: Fraction`, `_decimal` | Exact costs for non-terminating unit costs (§3.2). |
| `LotReplay.costs`, `line_costs` | The fold, the budget, `positions` and `realised` must read one set of lot-derived costs (§2.4). |
| `_foreign_currency`, `lots_for` | The fold readers replay currencies only, so a security error cannot fail `net-worth` (§3.1). |
| `currency_lines_service` | One query for every line the currency replay needs, on every account (§3.5). |
| `UnitBalance.kind`, `FifoHolding.kind` | Rates need 8 decimals, and subtotals need to know currency rows (§8.2). |
| `CurrencyWithPeople`, `NotACurrencyUnit`, `CurrencyLineNotAtPar`, `ConversionBetweenCurrencies`, `CurrencyInflowWithoutRate`, `NonPositiveQuantity`, `NotAQuoteCurrency`, `RateNotQuotedInEur` | The spec's refusals, and V1–V6, as named values. |
| `Price.currency`, `PriceBinding.quote_currency` | A close names its quote currency (spec); per-row so that rebinding is safe (§5.1). |
| `fetch_bound_closes` | alphavantage must report the binding's currency, and the one-argument call is pinned (§5.3). |
| `PriceTargets.quote_currencies` | Validation is per unit, and the plugin needs the binding's currency. |
| `_quote`, `ValuedBalance.rate`, `Position.rate`, `valuation_status` | Valuation needs a close and a rate, with the worse status (§8.1). |
| `Subtotal`, `subtotals`, `holding_currencies` | Per-currency subtotals (spec) |
| `PositionsReport` | Subtotals need bindings, which only the use case can read (§8.3). |
| `ValuedNetWorthReport.subtotals` | The same, for `net-worth` |
| `EcbPriceFetcher`, `NsePriceFetcher` | Spec |
| The moves of `balance_sheet_accounts` and `BASE_CURRENCY` | The `journal ↔ lots` cycle, and the model defaults (§2.7) |

**Explicitly not introduced:**

- **a stored lot or stored derived euro value** (§2.3);
- **an exact price column type** (§4);
- **a separate fold for currencies.** The `costs` mapping makes the one fold
  exact;
- **a `Protocol` for valued rows**, **a currency-conversion step** and **a
  rate cache across reports**.

### Alternatives rejected

| Rejected | Where | Short reason |
|---|---|---|
| Store a lot-derived euro figure at record time | §2.3 | a backdated entry would leave it wrong |
| Materialise it and re-derive on every write | §2.3 | every mutation path, current and future, must remember; it rewrites recorded lines; it fails at write time, not report time |
| Two-amount line as `unit_price = X / Y` | §2.1 | not exact; `validate_lines` refuses it |
| Make `unit_price` nullable | §2.1 | rebuilds `journal_lines` and forces `None` handling into split and reclassify code that only sees EUR lines; a display figure plus an authoritative `cost` costs nothing |
| A "lot-valued" flag instead of `price_unit_id` | §2.1 | cannot balance per currency or apportion a payment |
| Balance lot-derived entries trivially (no check) | §2.1 | loses typo protection and the apportioning weights |
| Keep the fold moving-average for currencies | §2.4 | phantom gain on every purchase paid in rupees |
| Full replay (securities too) behind `net-worth` | §3.1 | a security shortfall would fail `net-worth` |
| `Decimal` unit cost for currency lots | §3.2 | 1,000 / 90,000 × 90,000 ≠ 1,000 |
| Lot total with proportional splitting | §3.2 | makes today's exact security splits inexact |
| Reuse `SecurityMoveWithPeople` for currencies | §3.4 | its pinned text says "securities" |
| Ignore People-only currency entries, as for securities | §3.4 | the who-owes-what fold would read rupees at par as euros |
| Store the rate as quoted | §4 | an inversion marker and a branch in every reader |
| Refuse rebinding while closes exist | §5.1 | a dead end with no price deletion |
| `Close.currency: str \| None` | §5.3 | breaks a pinned test; lets plugins skip the check |
| A second parameter on `fetch_latest_closes` | §5.3 | breaks one-argument plugins |
| `--eur X`, `--from-total`/`--to-total`, `record-fx`, `@@` | §6 | see §6.3 |
| `--rate` with a purchase | §6.1 | would realise FX on what the spec says realises nothing |
| SDMX endpoint for ECB | §7.2 | one request per currency, no extra information |
| NSE community libraries | §7.3 | unofficial, heavy, unmaintained |
| A function-level import to break the cycle | §2.7 | hides the cycle |

---

## 12. Issue mapping, order and scope changes

### 12.1 What lands where

| Issue | Lands |
|---|---|
| 107 | Migration A. `Price.currency`, `PriceBinding.quote_currency`. `set-price-source --currency` for securities. `validate_close(…, quote_currency)` and per-unit validation in `AppendPrices`. `fetch_bound_closes`, with alphavantage overriding it. The `file` currency column. The `fetch-prices` currency suffix. `NonBaseCurrency` reworded. **Plus: capture the no-regression oracle (124) as the first commit, from pre-feature code.** |
| 108 | `SetPriceSource` binds non-base currency units, quoted in EUR only. `ListPriceTargets` adds held currency units **and the quote currencies of held securities** (scope addition, §5.4). |
| 109 | `ecb` (§7.2). |
| 110 | `nse` (§7.3). |
| 111 | Migration B, `cost`. `Total`, `record --total`. `_replayed` widened; `Lot.unit_cost: Fraction`; acquisitions at stated cost. `JournalLine.value` honours `cost`. **Scaffold:** INR now appears as a `positions` row, with a `.2f` price, until 120 and 121 format it. |
| 112 | Docs and tests for openings: the 111 form with an opening account, for INR and for a security. |
| 113 | Migration C, `price_unit_id`. `validate_lines` per price currency (V1, V3, V4, V6), and V2 where `--currency` is resolved. `record --currency` with a unit and a price or total. The per-entry replay (§3.3). `line_costs`, `currency_lines_service`, `costs` in the folds. The module moves (§2.7). `UnitBalance.kind`, `FifoHolding.kind`. |
| 114 | `record --currency` without a unit (an at-par expense). The budget reads `costs`. The `entries-in-period` `priced in` column. |
| 115 | `--from-unit C --total X`: a disposal with `Sale` rows of unit `INR`. **Now also depends on 113** (the fold's FIFO costs). |
| 116 | `CurrencySide.rate`, `record --rate`, V5 and `CurrencyInflowWithoutRate`. |
| 117 | `CurrencyWithPeople`. Moves at par. Tests that `positions`, `realised`, `balance` and `net-worth` fail as a whole. |
| 118 | The insertion-order test, **using distinct dates for entries that touch the same lots** (§13.1). |
| 119 | The `record-split` `=T` total and its sixth field. |
| 120 | `_quote`, rows' `rate`, `valuation_status`. The `quoted in` column and rate formatting in `balance` and `net-worth`. |
| 121 | `positions` with `quoted in` and the INR row's formatting. |
| 122 | `Subtotal`, `subtotals`, `holding_currencies`, `PositionsReport`, `ValuedNetWorthReport.subtotals`, and the CLI tables. |
| 123 | Tests and docs only. History values through `value_balances(as_of)` already. |
| 124 | Compares every command's output against the oracle captured in 107. |
| 125 | Docs. |

### 12.2 Order

**Proposed:** 107 → 108 → 109 → 110 → 111 → 112 → **120** → 113 → 114 → 115 →
116 → 117 → 118 → 119 → 121 → 122 → 123 → 124 → 125.

- **120 moves ahead of 113.** Its declared dependencies (107, 111) are met,
  and it makes `net-worth` correct for Indian holdings entered as openings
  (112) six slices earlier. That is the spec's opening motivation.
- **Purchases paid in rupees (113) do not touch the valuation code.** They
  only add `costs` to the fold.
- **Otherwise the order is the numeric one.** 113–117 share `lots.py` and
  `journal.py`, so they land in sequence.

---

## 13. Gaps in the spec, and points for the user

1. **Same-date entries break the testable order-independence claim.**
   - Ties within a date are broken by line id, which is insertion order.
   - Two remittances on one date, recorded in either order, give their lots
     different FIFO order. A later purchase then costs differently, and both
     answers are "a full replay in `(entry_date, line id)` order".
   - The design satisfies the definition. Test 118 uses distinct dates for
     entries touching the same lots.
   - **Decided:** insertion order stays the tiebreak. The spec now says
     the claim holds across distinct dates only.
2. **The rate convention.**
   - The spec says the lot costs "amount × rate", which is euros per rupee
     (0.00953612).
   - It also says the user "typically looks up the ECB rate", which the ECB
     quotes as rupees per euro (104.8645).
   - The design follows the formula: `--rate` is euros per unit, and the docs
     show how to invert.
   - **The user may prefer** a per-euro form instead, such as `--rate-per-eur
     104.8645`. That would add a rounding rule: the cost would be quantised
     to 8 places.
3. **The rate is fetched for quote currencies, not only held currencies.**
   With every rupee spent on shares, INR is not held, and the shares would
   never be valued. The design widens 108 (§5.4).
4. **"Usage error" for a rate-less inflow.** A sale is caught as a flag error
   (exit 2). A dividend is refused by the use case (exit 1), because only the
   accounts tell it from a move. Every domain refusal in kohle exits 1.
5. **alphavantage must be told the binding's currency.** The one-argument
   contract call is pinned by existing tests, hence `fetch_bound_closes`
   (§5.3). The behaviour is the spec's; the mechanism is a compatible
   contract addition.
6. **"`set-price-source` stops refusing currency units (`NotASecurityUnit`)"
   against a pinned test.** `test_set_price_source.py` and `test_price_cli.py`
   pin `NotASecurityUnit` ("is a currency, not a security") for EUR. The base
   currency, and commodities, keep that refusal. Only non-base currency units
   become bindable.
7. **Subtotals print only when some holding's currency is not EUR.** That is
   required by "no regressions". Read literally, the spec's `-` rule also
   makes the **EUR** subtotal's native figure `-` whenever an EUR member is
   at cost, such as an unbound security. **The user may want** the EUR row
   omitted, or its native figure taken as the euro figure.
8. **People.** The Goals refuse a currency moving "between an own account and
   a People account". The design refuses **any** currency line on a People
   account, which the Non-Goal's wording covers (§3.4).
   - **Practical effect:** an expense paid in rupees and split with a friend
     is recorded as the full payment, and the friend's share is moved in
     euros in a second entry. The docs say so.
9. **`entries-in-period` shows face values.** An expense paid in rupees lists
   `1500.00`, `priced in INR`. Its euro cost appears in `balance` and
   `budget` (§2.5). **The user should say** if euro values are wanted there.
   That needs a listing use case over `line_costs`.
10. **Debts in a currency.** Spending rupees from an account with no rupee
    lots (an INR credit card, say) is a `LotShortfall`. Foreign-currency
    liabilities belong to the `debts-and-liabilities` brief.
11. **Refunds and compensations of an expense paid in rupees.** An at-par
    credit to an expense account is refused (V5), so a refund is recorded as
    an inflow at a rate. An exact reversal that restores the original lots
    is not expressible. This matters to the `undo-delete-edit` brief.
12. **For a currency unit, `balance`'s `average cost` is FIFO, not a moving
    average** (§2.4). The docs state it beside the existing "moving average
    versus FIFO" sentence, which still holds for securities.
13. **The no-regression oracle (124) must be captured before 107 lands.**
    Pre-feature output cannot be produced afterwards.
14. **`fetch-prices`' `N held securities unpriced` counts currency units
    too.** The wording is kept so that EUR-only output does not change.
15. **`nse` and the `BE` series.** A stock moved to trade-for-trade becomes
    `no_symbol`. This is the spec's `EQ` rule, surfaced in the detail text.
16. **The terms of use are unverified for NSE, and verified for the ECB**
    (§7.1).
17. **A pre-existing inexactness, observed and not fixed.** `record --to-price`
    stores the cash side as an unquantised quantity × price. A product past 8
    decimal places is rounded on storage, so a stored entry can be out of
    balance by under 10⁻⁸. The new forms quantise (§6.1). Fixing the old path
    is a separate `change`.
18. **Opening account type.** The spec says "an opening account the user
    names". The docs recommend `--type income`, so that openings raise net
    worth. An asset-type opening account would cancel them.

---

## 14. Testing notes

The existing layers are extended: pure functions, use cases against
`session` (with `people_root`), the CLI through `CliRunner`, the guards, and
the migrations. Every number below is fictional. ISINs and codes in tests
are fictional too (`INR` is a real code; the units built around it are not).

**Pure (`replay`):**

- **111.** A remittance (`cost=1000`, 90,000 INR) gives one INR holding of
  exactly `Decimal(1000)`.
- **113.** The spec's 1,000/90,000, 1,100/100,000, then 120,000 example gives
  a stock lot of 1,330, INR 70,000 at 770, no `Sale`, and `costs` of
  1,330 on both purchase lines.
- **Apportioning.** One payment for two stocks splits exactly, and the shares
  sum to the consumed cost.
- **The partial load.** The same entry with an at-par expense line missing
  gives the stock its own share.
- **115.** A reconversion gives a `Sale` of unit INR with proceeds, FIFO cost
  and gain.
- **Moves.** INR at par from A to B carries its lots: no `Sale`, and B's
  later payment uses A's costs.
- **Shortfall** on a payment and on a disposal, with the exact `LotShortfall`
  text.
- **`CurrencyWithPeople`** for a People credit, a People debit and a
  People-only entry.
- **`lots_for=_foreign_currency`** ignores a security shortfall in the same
  ledger.
- **All existing `test_lots.py` cases unchanged.**

**Pure (`journal`):**

- The fold with `costs` is FIFO for a currency, giving the spec's 2,100
  total and no 2,103.68.
- Without `costs` the fold is identical to today (`test_average_cost.py`
  unchanged).
- `validate_lines` V1 and V3–V6, one case each, and V2 at name resolution
  in both record use cases. A base-currency imbalance gives today's message.

**Pure (`reporting`):**

- `_market_value` with a rate.
- `valuation_status` for all combinations, including a stale rate with a
  fresh close, which shows the rate's date.
- `subtotals` with a `-` member, a zero row and an EUR-only set (`[]`).

**Use cases:**

- `record --total` stores `cost`; `record --currency` builds at-par lines;
  `--rate` quantises.
- An inflow without a rate is `CurrencyInflowWithoutRate` and writes
  nothing.
- `SetPriceSource` binds INR in EUR and refuses INR in USD. EUR and
  commodities are still `NotASecurityUnit`.
- `ListPriceTargets` includes INR when only INR-quoted shares are held.
- `AppendPrices` rejects an INR close for an EUR binding and an EUR close for
  an INR binding, each leaving `prices` unchanged (the spec's testable), and
  stores `currency`.
- `QueryBudget` counts an expense paid in rupees at lot cost.

**Plugins**, through their seams with recorded fixtures and no network:

- **`ecb`:** INR present, an unknown code, a malformed body and two cubes.
- **`nse`:**
  - a weekend and holiday walk-back;
  - the 10-weekday limit;
  - a missing column;
  - a `BE`-only ISIN;
  - a duplicate `EQ` row;
  - an unreachable host.
- **`file`:** a 4-column header, and an empty currency cell.
- **alphavantage:** the binding's currency is stamped, and its
  one-argument call still says EUR.

**CLI and docs examples:**

- EUR-only tables are byte-identical: no `quoted in` column, no subtotals,
  `.2f` prices.
- With INR, the column, the 8-decimal rates and the subtotal table appear.

**Order independence (118):** the same entries recorded in two insertion
orders, with a remittance, a purchase, a reconversion, a rated inflow and a
backdated entry, all on distinct dates. `positions`, `realised`, `balance`
and `net-worth` give identical output.

**No regression (124):** the oracle captured in 107, compared for every
command on an EUR-plus-securities ledger.

**Migrations (§9):** a round trip and a refusal for each of A, B and C.

**Guards:**

- `lots.py` stays in `_guarded_sources` and `RECORDING_MODULES`. Now that
  `journal` imports `lots`, the transitive test covers it twice over.
- `PRICE_ENTRY_POINT_NAMES` may stay `{"file", "alphavantage"}`. The
  no-price-plugins test still passes with `ecb` and `nse` installed, since
  its script never binds them. Adding them is optional and does not change
  what the test proves.

**After landing.** `AGENTS.md`'s Context should gain a sentence. The user
edits it; this design does not. Proposed text:

> A line may be priced in a non-base currency unit (`price_unit_id`); its
> euro value is never stored but derived by `kohle/use_cases/lots.py` from the
> currency's FIFO lots on every read, and the moving-average fold takes those
> costs through `line_costs`. A rate is an ordinary price of a currency unit in
> EUR, and every stored close names its currency.

## Decisions confirmed by the user

The user accepted every recommendation in the architect's hand-back:

- Same-date ties: entries on one date are ordered by insertion; the order-independence claim holds for distinct dates only. The spec carries the matching caveat.
- `--rate` is euros per unit of the currency (the spec's amount x rate), not per euro.
- A rate-less dividend is refused after the ledger is opened (exit 1); a rate-less sale is a flag error (exit 2).
- Subtotals print only when a non-EUR currency is present.
- Any currency line on a People account is refused, including between two people.
- `entries-in-period` shows an INR expense in rupees with a `priced in` column.
- `set-price-source EUR` still fails with `NotASecurityUnit`.
- Issue scope and order changes as proposed; 120 is implemented before 113.

## Implementation notes

Findings made while building issues 107-125; none changes a decision above.

- **Baseline for 124.** The design left the file and format open. The first
  slice-107 commit holds `tests/pre_feature_baseline.py` (its
  `run_script(session_factory)` returns the text, with today pinned to
  2026-06-15) and `tests/fixtures/pre_feature_baseline.txt`, the output of 69
  commands on a EUR-and-securities ledger. `test_multi_currency_regression.py`
  compares against it byte for byte.
- **`lots_for` default.** §3 writes `replay(..., lots_for=_replayed)`, which
  contradicts the rule that a unit with no kind takes the security path
  (`test_lots.py` calls `replay` with kind-less units). The default is every
  unit; `replay_ledger` passes `_replayed` and `line_costs` passes
  `_foreign_currency`.
- **`holding_currencies`** takes the valued rows rather than `unit_ids`: the
  signature in §8 cannot tell a currency unit (bound, quoted in EUR) from a
  bound security.
- **Open decision 7** is implemented literally: the EUR subtotal row's native
  figure is `-` whenever a EUR member is valued at cost.
- **Not covered, left open.** An entry whose lines are all priced in INR with
  no INR line to pay them gets no lot-derived cost, and the fold reads the INR
  face as euros. `record-split` can produce it. A guard would also reject a
  legitimate move of INR-priced securities, so it needs a decision.
- **Messages the design did not give:** `RateNotQuotedInEur`, the `nse`
  `Unavailable` detail, and the `--currency` help text on `set-price-source`
  (still says "EUR or an existing currency unit").
- **Not verified:** `mkdocs build --strict` (mkdocs is not in the project
  environment) and a recorded live fetch for the `ecb` test body, which is
  hand-written to §7.1's structure.
- **AGENTS.md** still lacks the Context sentence proposed above; that edit is
  the user's.
