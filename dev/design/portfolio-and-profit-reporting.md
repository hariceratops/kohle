# Design: Portfolio and profit reporting

Spec: `dev/specs/portfolio-and-profit-reporting.md` (frozen)
Issues: `dev/issues/040`–`046`
Precedent: `dev/design/market-value-reporting.md`, cited as MV §n.

Layering per `AGENTS.md` stays `app -> use_cases -> services ->
infrastructure/domain`. Only services touch a `Session`. Functions return
`Result[T, E]`; domain errors are `Exception` subclasses used as values.

Gaps found in the spec are collected in §14. Where the design had to choose
behaviour the spec leaves open, the choice is made, marked there, and left for
the user to confirm.

---

## 1. Summary of the shape

| File | Change | Issue |
|---|---|---|
| `kohle/use_cases/journal.py` | `BalanceSheetAccounts` and `balance_sheet_accounts(ctx)`, the net-worth partition, factored out of `net_worth` (§3.2). `NetWorthLines` and `net_worth_lines(ctx)` factored out next (§5.4). `net_worth` becomes their composition plus the two folds. `_unit_balances` is extracted from `aggregate_by_unit`, and `aggregate_by_unit_through(lines, dates)` is added (§5.4). Nothing here names a price. | 040, 045 |
| `kohle/use_cases/lots.py` | **new**, price-free and under the guard (§2). It holds `Lot`, `Sale`, `FifoHolding`, `LotReplay`, `replay`, `replay_ledger`, `realised_gain` and `QueryRealised`. | 040–043 |
| `kohle/use_cases/sampling.py` | **new**. 045 adds `period_end` and `sample_dates`. 046 adds `PeriodEnd`, `STATES` and `working_days`, and gives `sample_dates` the mode and state. This is the only module that imports `holidays` (§6). | 045, 046 |
| `kohle/services/price_services.py` | `latest_price_service` gains `on_or_before: date \| None = None` (§5.1). | 045 |
| `kohle/use_cases/prices.py` | `latest_close(ctx, unit_id, as_of, max_age_days=7)` reads the latest close on or before `as_of` (§5.2). | 045 |
| `kohle/use_cases/reporting.py` | 044 adds `_market_value`, `Position`, `ValuedRow`, `fifo_cost`, `unrealised_gain` and `QueryPositions`, and types `at_market` and `summarise` over `ValuedRow` (§8). 045 adds `valued_net_worth(ctx, …)`, factored out of `ValuedNetWorth`, plus `HistoryRow` and `NetWorthHistory`, and renames `value_balances`' `today` to `as_of` (§5). 046 passes the mode and state through `NetWorthHistory`. | 044–046 |
| `kohle/domain/domain_errors.py` | `LotError`, `RealisedError` (040); `LotShortfall` (041); `UnbalancedOwnMove` (042); `SecurityMoveWithPeople` (043); `PositionsError` (044). | 040–044 |
| `kohle/app/cli/cli.py` | `realised` (040), `positions` (044) and `net-worth-history` (045, 046). `_market_columns` is typed over `ValuedRow` (044). | 040, 044–046 |
| `pyproject.toml`, `uv.lock` | `holidays==0.106` (§6.3) | 046 |
| `tests/test_price_guards.py` | Puts `lots.py` under the price-free guard. Extends the price-writer guard to the three callbacks and `lots.py`. Adds a read-only test that also counts `operation_groups` (§15). | 040, 044, 045 |
| `README.md` | "Positions and profit" and "Net worth over time" (§10.4) | all |

No schema change, no migration. One new runtime dependency.

**Import direction.**

```
cli ──► reporting ──► lots ──► journal
 │          │  └────► sampling          (holidays, imported lazily)
 │          └───────► prices ──► journal
 ├────► lots       (QueryRealised, realised_gain, Sale)
 └────► sampling   (STATES, PeriodEnd)
```

- `journal.py` imports none of `lots`, `sampling` or `reporting`.
- `lots.py` imports nothing from `prices` or `reporting`. The guard enforces this (§2.2).
- The graph is acyclic.

---

## 2. Where the FIFO replay lives (decision 1)

### 2.1 Its own module, `kohle/use_cases/lots.py`, price-free

**Not `journal.py`.**

- The guard would allow it, since the replay names no price. Nothing *forces*
  it there, though.
- The read-side residents of `journal.py` are there for specific reasons, which
  MV §2.3 records:
  - `aggregate_by_unit` and `account_balance` stay because `splitting.py`
    imports them;
  - `held_units` stays because `prices.py` imports it;
  - `net_worth` stays because `NetWorth` and its tests are pinned there.
- The replay has no such importer. It also brings its own value types, its own
  errors and its own use case. `journal.py` is already 720 lines, most of them
  recording and import, and would only grow.

**Not `reporting.py`.**

- `reporting.py` must import `kohle.use_cases.prices`, so it can never sit under
  the price-free guard.
- A replay there could start reading a stored close, and no test would notice.
- The spec's figures are gross and computed from *recorded* unit prices. A
  fetched close leaking into FIFO cost is exactly the bug class worth making
  structurally impossible.

**Its own module, under the guard.**

- This makes "realised gain depends only on the ledger" a property a test
  checks. It does not rest on a reviewer remembering it.
- `QueryRealised` lives beside the replay. `realised` reads no price, so the
  whole of `realised`'s use-case code is guarded.
- `QueryPositions` reads closes, so it lives in `reporting.py` and imports the
  replay from `lots.py`.
- **The name is `lots.py`.** Modules under `use_cases/` are domain nouns
  (`accounts`, `journal`, `prices`, `rules`, `splitting`, `units`). FIFO is the
  consumption order, and the module docstring says so.

### 2.2 The guard extension

| Guard | Change |
|---|---|
| `_guarded_sources()` (static: names no `Price`, `PriceBinding`, `PriceFetcherPlugin`, `load_price_plugins`, and no price module) | gains `"kohle/use_cases/lots.py"` |
| `RECORDING_MODULES` (transitive: importing it loads no price module) | gains `"kohle.use_cases.lots"` |
| `_report_sources()` (names no price writer) | gains `"kohle/use_cases/lots.py"` and the callbacks `realised_cmd`, `positions_cmd`, `net_worth_history_cmd` |

- **The names stretch.** `lots.py` neither records nor imports.
  `_guarded_sources()` already stretches the same way by holding
  `importer_plugin.py`.
- **Renaming was rejected.** It would rewrite the identifiers of existing tests
  for no behaviour change. A one-line comment at `RECORDING_MODULES` says why
  `lots` is in it: realised gain must come from recorded prices only.
- **Each change only adds parametrised cases.** No existing case changes, which
  keeps the spec's "every existing test passes unchanged".

### 2.3 What stays where it is

- `QueryAccountBalance`, `NetWorth` and `ValuedNetWorth` keep their signatures.
  MV §2.3 lists the tests that pin them.
- `balance` and `net-worth` output does not change. The only observable change
  is in §5.2: a stored close dated after `today` is no longer used, and
  `fetch-prices` cannot write one.

---

## 3. Recognising purchases, sales and moves (decision 2)

### 3.1 The account on each line

- **The account id is already there.** `JournalLine.account_id` is a column, and
  `account_lines_service` already returns it.
- **Membership decides own versus People.** A line's account id is looked up in
  the partition maps (§3.2), which hold own accounts and People accounts.
- **The same maps supply the names.** The `realised` `account` column and the
  error messages need account names, and the maps carry them.
- **No service change.** `account_lines_service` keeps loading `entry` and
  `unit` only.

**Rejected: `joinedload(JournalLine.account)` in `account_lines_service`.**

- It adds a join to every balance and net-worth fold.
- It edits the one service whose ordering comment says it is load-bearing.
- It recovers names that the partition query has already loaded in the same
  transaction.

### 3.2 The partition, `balance_sheet_accounts(ctx)`, factored out of `net_worth`

```python
@dataclass(frozen=True, slots=True)
class BalanceSheetAccounts:
    own: dict[int, str]       # account id -> name
    people: dict[int, str]    # account id -> name


def balance_sheet_accounts(ctx: DbTransactionContext) -> Result[BalanceSheetAccounts, AccountError]
```

**Same queries as today.** These are the queries `net_worth` runs now:

- the People root by name;
- its descendants;
- `list_accounts_service`.

**The sets are the same as today's.**

- `own` holds the `asset` and `liability` accounts outside the People subtree.
- `people` holds the People subtree, of any type.

These are exactly `balance_sheet_ids - people_ids` and `people_ids` in today's
`net_worth`.

**Why it is factored out.** The spec says `positions` sums over "`net-worth`'s
own-accounts partition".

- A second copy of the partition in `lots.py` would give "own account" two
  definitions.
- This is the same move MV §2.4 made with `net_worth(ctx)`: it was copied from
  nowhere, and called from two places.

**It returns maps, not id sets.** One `dict` answers both "is this own?" and
"what is it called?". `net_worth` uses `.keys()`.

**It inherits `net_worth`'s People-root lookup.** Without a `People` account,
`positions` and `realised` fail with `AccountNotFoundError(People)`, as
`net-worth` does today. The migration seeds the root, and tests use the
`people_root` fixture.

### 3.3 The rule

The replay groups lines by entry and, within an entry, by unit. Only two kinds
of line are in view:

- lines of replayed units (§4.1);
- lines on own or People accounts, because nothing else is loaded.

For each entry E and unit U, the U-lines of E decide what E is:

| U-lines of E | For U, E is | Effect |
|---|---|---|
| at least one on a People account **and** at least one on an own account | unsupported | `Err(SecurityMoveWithPeople)`; the report fails (043) |
| on own accounts, some credited **and** some debited | an own-depot move | lots move with their original dates and costs; nothing is realised (042) |
| on own accounts, credited only | one sale per credited line | lots are consumed FIFO from that depot, and a `Sale` row is emitted |
| on own accounts, debited only | one purchase per debited line | a `Lot(entry date, line id, quantity, line unit price)` joins that depot's queue |
| on People accounts only | nothing replayed | ignored |

What the rule means in practice:

- **Counter-lines never matter.** The rule reads only U-lines. EUR cash, other
  units and income or expense accounts are all invisible to it. So all of these
  are sales:
  - a sale for cash;
  - a sale against a receivable, e.g. `Depot cr X` with `Alice dr EUR`;
  - a write-off against an expense account. Recorded at price 0, its proceeds
    are 0 and its gain is minus the cost.

  A bonus share received in kind from an income account is a purchase at its
  recorded price.
- **The rule is per unit, not per entry.** `Depot cr X` with `Alice dr EUR` is a
  sale to Alice. An entry becomes unsupported only when there is a People line
  *in the security itself*. That is the spec's "a security moving between an own
  depot and a People account".
- **A move must balance.** The quantity credited must equal the quantity debited
  across own accounts. Otherwise the result is `Err(UnbalancedOwnMove)`, which is
  a design addition (§14.2). An unequal entry could be "move 6 and sell 4" or
  "move 6 and write off 4", and the spec's own stance is to fail rather than
  guess (043).
- **How lots travel in a move:**
  1. Each sending line, in line-id order, takes its quantity from the front of
     its depot's queue. A shortfall fails as in 041.
  2. The taken lots are pooled and ordered by original purchase.
  3. They are dealt to the receiving lines in line-id order, splitting a lot at a
     boundary.
  4. Each lot is inserted into its receiving queue in purchase order.

  The move lines' recorded prices are ignored, because the lots keep their own
  costs.
- **A self-move is harmless.** A depot credited and debited for U in one entry is
  a move from itself to itself. The lots return with their original keys, so the
  order does not change.
- **The rule is "credited and debited", not "every U-line is on an own account".**
  The rejected alternative misreads an entry like `A cr X 10`, `B dr X 6`,
  `Expense dr X 4`. Not every U-line is on an own account, so it would read A's
  credit as a sale of 10 and B's debit as a fresh purchase of 6. B's lots would
  lose their original dates and costs, and gain would be realised on shares that
  only moved. The chosen rule recognises the move and fails on the imbalance.
- **How the user records a move.** `record` cannot express a move, because one
  of its sides is always EUR. `record-split` can, and the README gains this
  example (042):

  ```bash
  kohle-cli record-split 2026-05-01 "Move to DepotB" \
      --line DepotA:10:IE00B4L5Y983:100:credit \
      --line DepotB:10:IE00B4L5Y983:100:debit
  ```

  Any equal price balances the entry, and FIFO ignores it.
- **A sale and a repurchase in one entry are read as a move.** The README tells
  the user to record them as two entries.

---

## 4. The replay

### 4.1 The one filter

```python
def _replayed(unit: Unit) -> bool:
    return unit.kind is UnitKind.security
```

- **Where it runs.** It is applied in `replay_ledger` to the loaded lines,
  before `replay`.
- **It is the only place `security` appears in the feature.** It selects:
  - the `realised` rows;
  - the `positions` rows;
  - the units the shortfall and People checks apply to.
- **Everything downstream is kind-agnostic:** `replay`, `Lot`, `Sale`,
  `FifoHolding`, `Position` and the valuation. §8.4 covers what widening the
  filter later means.
- **Why the checks follow the filter.** A foreign-currency cash account that
  goes negative must not make `positions` fail, and it does not, because
  currencies are not replayed.

### 4.2 Types (all frozen, slotted dataclasses)

```python
class Lot:
    acquired: date          # the acquiring line's entry date
    line_id: int            # the acquiring line's id; (acquired, line_id) is the FIFO order key
    quantity: Decimal
    unit_cost: Decimal      # the acquiring line's unit price

    @property
    def cost(self) -> Decimal: ...          # quantity * unit_cost


class Sale:
    entry_date: date
    account_name: str
    unit_identifier: str
    quantity: Decimal
    proceeds: Decimal       # quantity * the sale line's unit price
    fifo_cost: Decimal      # sum of the consumed lots' cost

    @property
    def gain(self) -> Decimal: ...          # proceeds - fifo_cost


class FifoHolding:
    unit_identifier: str
    unit_id: int
    quantity: Decimal       # remaining lots, summed over own depots
    fifo_cost: Decimal


class LotReplay:
    sales: list[Sale]               # ledger order
    holdings: list[FifoHolding]     # nonzero only, in first-seen unit order
```

- **Why `Lot` stores `unit_cost` and not `cost`.** A partly consumed lot is split
  into two `Lot`s with the same `unit_cost` and exact `Decimal` quantities.
  Storing a lot's total cost would force `cost * part / quantity` on every split.
  That is a 28-digit quotient, and it would make a `NoClose` row's unrealised
  gain come out as `1E-26` rather than 0 (the spec's testable "gain 0").
- **Why the order key is `(acquired, line_id)`.** It is the spec's ledger order,
  `(entry_date, line id)`, taken from the purchase line. Moved lots keep it, so
  the receiving queue is in original purchase-date order with deterministic ties.
- **`FifoHolding` is the FIFO twin of `UnitBalance`.** It carries `unit_id` for
  the close lookup, as MV §3 did for `UnitBalance`. It stays a separate type
  because the two folds have different cost semantics (§8.2).
- **Sales carry the account name, not the id.** `Sale` crosses into the CLI after
  the session has closed.

### 4.3 `replay(lines, own, people) -> Result[LotReplay, LotError]`

This function is pure, so it is tested without a database.

**What it expects of its input:**

- `lines` is in `(entry_date, line id)` order, which `account_lines_service`
  guarantees.
- `lines` is already filtered by `_replayed`.
- Every line has `entry` and `unit` loaded.

**The algorithm:**

1. Group the lines by `(line.entry.id, line.unit.identifier)` into a `dict`.
   Insertion order is the ledger order of each group's first line.
2. For each group, split its lines three ways:
   - `outs`: own credits;
   - `ins`: own debits;
   - `with_people`: lines on People accounts.

   Then apply §3.3.
3. Keep the queues in `dict[tuple[int, str], list[Lot]]`, keyed by
   `(account_id, unit identifier)`. Each list stays sorted by the order key.
4. Keep `dict[str, int]` mapping each identifier to the `unit_id` first seen,
   for `FifoHolding`.
5. Build the holdings at the end. For each identifier, in first-seen order, sum
   quantity and cost over every queue of that identifier, and keep it when the
   quantity is not 0.

**Two keying choices exist for the pure tests:**

- **Group by `line.entry.id`, not `line.entry_id`.** Pure tests build transient
  `JournalLine(entry=JournalEntry(id=…, entry_date=…), …)` objects, whose
  `entry_id` column stays `None` until a flush. Grouping by it would merge every
  test line into one entry.
- **Key queues by unit identifier, not `unit_id`.** `aggregate_by_unit` groups by
  identifier for the same reason (MV §3): transient lines carry `unit_id=None`.
  The `None` reaches `FifoHolding.unit_id` only in pure tests, which value
  nothing.

**Which check runs first.** Within a group, the People check runs first, then
the move balance, then shortfalls in line order. The first failure in ledger
order ends the replay. That is the spec's "fail as a whole".

### 4.4 Consumption, `_take`

```python
def _take(queue: list[Lot], quantity: Decimal) -> tuple[list[Lot], Decimal]
```

- **What it does.** It removes up to `quantity` from the front of `queue`.
  It returns the lots taken, the last of which may be split off, and the
  shortfall, which is `Decimal(0)` when the queue covered the quantity.
- **It has three uses, so FIFO taking is written once:**
  - a sale;
  - a move's sending line;
  - dealing the pooled lots to a move's receiving lines. Here the shortfall is
    0 by the balance check.
- **On a shortfall above 0** the result is
  `Err(LotShortfall(unit, own[account_id], entry_date, shortfall))`.
  - The queue is left mutated. That is fine, because the `Err` discards the
    whole replay.
- **Insertion uses one rule:** `bisect.insort(queue, lot, key=_acquisition)`.
  - A purchase's key is the largest seen so far, because lines arrive in ledger
    order. So `insort` appends it.
  - A moved lot lands in purchase order.
  - Both cases share the one rule.

### 4.5 `replay_ledger(ctx)` and `QueryRealised`

```python
def replay_ledger(ctx: DbTransactionContext) -> Result[LotReplay, RealisedError]:
    # balance_sheet_accounts(ctx)
    # account_lines_service(ctx, own ids | people ids)   -- one ordered load
    # replay([l for l in lines if _replayed(l.unit)], accounts.own, accounts.people)


def realised_gain(sales: Iterable[Sale]) -> Decimal      # sum of gain, the mirror of at_market


class QueryRealised(UnitOfWork[list[Sale], RealisedError]):
    def execute(self, year: int | None) -> Result[list[Sale], RealisedError]: ...
```

- **One load, not two.** Own and People lines come back in a single
  `account_lines_service` call, so the lines of one entry arrive together, in
  one ordered list. `net_worth` loads the two sections separately, and merging
  them back by entry would be extra code for nothing.
- **The year filter is in the use case**, on `sale.entry_date.year`, after a
  replay over the full history. A TUI then gets the same rows. The total is
  `realised_gain` over the filtered list. The CLI sums nothing (expense-splitting
  §9.3).
- **The return is a bare `list[Sale]`.** The whole report is one list with one
  total, which is MV §4.5's reasoning for `balance`. A wrapper type would have no
  forcing problem.
- **Cost of loading everything.** The load returns every line of every own and
  People account, mostly EUR bank lines, and then filters in Python. That is the
  same load `net-worth` already does on every run. A kind filter in SQL would
  need a new service parameter to save one report's hydration time. Rejected for
  now (§12, Alternatives).

### 4.6 Errors

All are new, in `domain_errors.py`, as subclasses of `LotError(Exception)`:

| Error | Fields | Message (the spec's required content in bold) |
|---|---|---|
| `LotShortfall` | `unit_identifier, account_name, entry_date, shortfall` | `"{**unit**} in {**account**!r} on {**date**}: disposes of {**shortfall**} more than the account holds; is an earlier purchase missing?"` |
| `SecurityMoveWithPeople` | `entry_id, entry_date, unit_identifier, own_account, people_account` | `"Entry {**id**} on {date} moves {unit} between own account {own!r} and People account {person!r}; moving securities to or from people is not supported yet"` |
| `UnbalancedOwnMove` | `entry_id, entry_date, unit_identifier, moved_out, moved_in` | `"Entry {id} on {date} moves {out} {unit} out of own accounts but {in} in; record the move and any sale or purchase as separate entries"` |

- **Quantities print as `f"{q.normalize():f}"`.** That gives `5`, `0.5` and `50`.
  A `Numeric(20, 8)` value read back from SQLite would otherwise print as
  `5.00000000`. `normalize()` alone would give `5E+1` for 50, which is why `:f`
  follows it. This is the only place the feature formats a quantity for prose.
- **Entries are named by id**, the handle `entries-in-period` prints first.
- **Where each error is used:**
  - `RealisedError = BalanceError | LotError`, for `replay_ledger` and
    `QueryRealised`;
  - `PositionsError = BalanceError | LotError | PriceError`, for
    `QueryPositions`;
  - `net-worth-history` runs no replay, so it keeps `ValuationError`.

---

## 5. Reading a close as of D (decision 3)

### 5.1 The service: one query, one optional bound

```python
def latest_price_service(
    ctx: DbTransactionContext, unit_id: int, on_or_before: date | None = None
) -> Result[Price | None, PriceError]
```

- **What changes.** When `on_or_before` is given, the query adds
  `Price.price_date <= on_or_before` before `ORDER BY price_date DESC`.
- **The index already covers it.** `uq_price_unit_date` is
  `(unit_id, price_date)`.
- **The fetch path is untouched.** `ListPriceTargets`, which orders requests,
  and `AppendPrices`, which reads the previous close, pass no bound and keep
  "latest overall".
- **Rejected: a sibling `close_on_or_before_service`.** It would be a second copy
  of the query that differs by one filter.

### 5.2 `latest_close` reads on or before `as_of`

```python
def latest_close(
    ctx: DbTransactionContext, unit_id: int, as_of: date, max_age_days: int = 7
) -> Result[LatestClose, PriceError]
```

**What it does.** It calls `latest_price_service(ctx, unit_id, on_or_before=as_of)`
and classifies the result relative to `as_of`, exactly as today. The age is now
never negative.

**Every reader goes through this, today included.** Bounding `latest_close` for
all callers, rather than adding a history-only reader, means:

- **`net-worth-history`'s final row and `net-worth` are the same computation.**
  They do not merely agree.
- **Today's behaviour changes only in an unreachable case.** `validate_close`
  rejects a close dated after the fetch day (`FutureCloseDate`). A stored close
  dated after `today` can therefore exist only if the clock went backwards
  between the fetch and the report.
  - Before this change, such a close was `Fresh` with a negative age.
  - Now it is skipped, and the previous close (or `NoClose`) is used.
  - That is the spec's rule, "never a later one", applied uniformly.
- **The rename is safe.** `today` becomes `as_of` here and on `value_balances`.
  Every test passes these positionally (`test_latest_close`, `test_reporting`),
  so it breaks nothing.

### 5.3 `value_balances` is unchanged except for the name

It still holds the lookup condition and still makes one `latest_close` read per
nonzero non-base row. History passes each sample date as `as_of`. This is the
switch MV's Extension points named: "`today` already flows down, so it would
become 'as of'".

### 5.4 Valuing a sample date D

**`net_worth_lines(ctx)`** (journal.py, factored out of `net_worth`):

```python
@dataclass(frozen=True, slots=True)
class NetWorthLines:
    own: list[JournalLine]
    receivables: list[JournalLine]


def net_worth_lines(ctx: DbTransactionContext) -> Result[NetWorthLines, BalanceError]
def net_worth(ctx: DbTransactionContext) -> Result[NetWorthReport, BalanceError]
    # net_worth_lines(ctx), then NetWorthReport(aggregate_by_unit(own), aggregate_by_unit(receivables))
```

- **Why it exists.** History loads the lines once, through the same definition
  of which lines net worth folds.
- **Why a type and not a tuple.** Two fields of `list[JournalLine]` would let a
  transposition type-check (the `EstimateSummary` rationale, MV §4.4).

**`aggregate_by_unit_through(lines, dates)`** (journal.py):

```python
def aggregate_by_unit_through(
    lines: Iterable[JournalLine], dates: Iterable[date]
) -> list[list[UnitBalance]]
```

- **What it does.** It folds `lines` once, in the order given. At each date in
  `dates`, which must be ascending, it snapshots `aggregate_by_unit` of the lines
  dated on or before that date.
- **Why one pass.** Re-folding a prefix per date is quadratic. On a synthetic
  12 000-line own section (about ten years of bank imports) with 240 samples:
  - re-folding each prefix through `aggregate_by_unit` took **4.64 s**;
  - one pass with snapshots took **0.048 s**, with identical `UnitBalance`
    lists (both measured).
- **It shares the fold.** It uses `_RunningCost`, and extracts
  `_unit_balances(running) -> list[UnitBalance]`, which `aggregate_by_unit` also
  returns through. The rows are therefore the same objects field for field.
  A test pins `snapshot == aggregate_by_unit(prefix)`.
- **`aggregate_by_unit` keeps its contract.** It stays order-dependent and
  date-blind. Its pure tests build lines with no entry, which it never reads.

**`valued_net_worth(ctx, report, as_of, max_age_days)`** (reporting.py):

```python
def valued_net_worth(
    ctx: DbTransactionContext, report: NetWorthReport, as_of: date, max_age_days: int
) -> Result[ValuedNetWorthReport, PriceError]
```

- **What it does.** It holds the two `value_balances` calls that
  `ValuedNetWorth.execute` makes today.
- **Who calls it.** `ValuedNetWorth` now runs `net_worth(ctx)` and then this.
  `NetWorthHistory` runs it once per date.

**Each history row is a `ValuedNetWorthReport`:**

```python
@dataclass(frozen=True, slots=True)
class HistoryRow:
    on: date
    report: ValuedNetWorthReport
```

- **Every column comes from it.** `at cost` is
  `report.at_cost.net_worth_at_cost`, `at market` is
  `report.net_worth_at_market`, and `K of M` is `report.estimates`. These are the
  same properties `net-worth` prints from.
- **So the final row equals `net-worth` by construction.** With `--to` today and
  no line dated after today:
  - the last snapshot is `aggregate_by_unit` of all lines;
  - it is valued by the same `valued_net_worth` at the same `today`.

  Future-dated lines break the premise (§14.1).

### 5.5 What a history costs

- **Close reads are linear.** There is one indexed read per held non-base unit
  per sample, about 0.7 ms each (measured in-memory through `latest_close`).
  Ten years at 24 samples, with ten held securities, comes to about 2400 reads
  and **about 1.7 s**. That grows linearly with years.
- **Accepted, because the alternative is a second read path.** Preloading each
  unit's closes and searching them in memory would need one.
  - It would be a callable "close reader" seam into `value_balances`, or a
    replica of the fresh/stale rule. MV §8 rejected the former for want of a
    forcing problem.
  - A second path is also what would let history and `net-worth` drift apart.
- **The line was drawn at quadratic.** The fold was made one-pass because it
  was quadratic. The reads were not, because they are linear and the one shared
  path is worth more.
- **When to revisit.** If a real ledger makes the report slow, the place to
  change is `value_balances`, with that measurement in hand.

---

## 6. Sample dates and working days (decision 5)

### 6.1 `kohle/use_cases/sampling.py`

```python
class PeriodEnd(Enum):                      # 046
    month_end = "month-end"
    last_working_day = "last-working-day"


STATES = ("BB", "BE", "BW", "BY", "HB", "HE", "HH", "MV",
          "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH")     # 046


def working_days(state: str) -> Callable[[date], bool]                   # 046, the predicate
def period_end(year: int, month: int, counts: Callable[[date], bool]) -> date
def sample_dates(start: date, end: date, mode: PeriodEnd, state: str) -> list[date]
```

**`period_end`** starts at the calendar last day and steps back one day at a
time until `counts(day)`.

- Under `month_end`, `counts` is `lambda _: True`, which gives the calendar last
  day.
- Under `last_working_day`, `counts` is `working_days(state)`.
- One function serves both modes. The mode only chooses the predicate.
- The loop has no guard against a predicate that never holds. A real calendar
  always has a working day in the last 16 days of a month, so that case is
  impossible.

**`sample_dates`:**

1. For each month from `(start.year, start.month)` to `(end.year, end.month)`,
   emit the 15th, then `period_end(…)`, keeping each that lies within
   `[start, end]`.
2. Then append `end`, unless it is already the last date.

What follows from this:

- **The list is ascending.** The period end is never before the 16th, because
  the last 16 days of a month always hold a working day.
- **Every date is at most `end`.** So if `end` is a sample date, it is already
  last.
- **The 15th never moves.**
- **There is no row at `start`.** The spec lists only the 15th, the period end
  and `--to`.

**The mode lives in `sampling.py`, not the use case.** The use case passes the
mode and state through, and only `sampling.py` knows a calendar exists.

**045 lands the calendar month-end form.** That is
`sample_dates(start, end)`, with `period_end(y, m, lambda _: True)` inline.
046 adds the `mode` and `state` parameters.

### 6.2 The predicate

`working_days(state)` builds the calendar once and returns:

```python
lambda day: day.weekday() < 5 and day not in calendar and (day.month, day.day) not in {(12, 24), (12, 31)}
```

`calendar` is `holidays.country_holidays("DE", subdiv=state)`.

- **This is the spec's "one small predicate".** Only this function knows where
  holidays come from. Swapping the source touches nothing in `period_end` or
  `sample_dates`.
- **The calendar is built once per report, not per date.** A `HolidayBase`
  answers `in` for any year, expanding lazily. This was checked against a year
  never requested.
- **The 24 and 31 December exclusion is needed.** It is not redundant with the
  calendar: `holidays` 0.106 lists neither date for any German state (verified).
- **Why a closure.** The calendar has to outlive one call. A class with one
  method would be the same thing with more lines.

### 6.3 The dependency

- **Pin.** `holidays==0.106` (the current release, checked on PyPI), pinned
  exactly in `pyproject.toml` like the other pinned runtime dependencies. Run
  `uv lock` to refresh `uv.lock`.
- **No new transitive package.** Its only dependency is
  `python-dateutil>=2.9.0.post0`, which is already pinned at that version.
- **`requirements.txt` is not touched.** It has been unmaintained since the
  initial commit, and it lacks `tabulate`, `pyparsing` and
  `python-statemachine`. Fixing it is a separate `change`.
- **The pin is part of the report's determinism.** A `holidays` release that
  corrects a state's calendar can move a period-end date. The spec's "same
  ledger, same prices, same today" is therefore also "same `holidays` version".
  The exact pin makes that true, and a deliberate bump is reviewable.

### 6.4 `STATES` is written out, and `holidays` is imported lazily

- **`holidays.Germany.subdivisions` is not the list of Bundesländer.** In 0.106
  it is the 16 state codes plus `"Augsburg"`, a city with its own holiday, the
  Friedensfest on 8 August. The spec says Bundesland, so `--state Augsburg` must
  be a usage error. The 16 codes are constitutionally fixed.
- **A contract test keeps the tuple honest.** It asserts that
  `holidays.country_holidays("DE", subdiv=s)` accepts every code in `STATES`, so
  the hand-written tuple and the pinned package cannot disagree unnoticed.
- **With the tuple written out, nothing needs `holidays` at module level.**
  `cli.py` needs only `STATES` and `PeriodEnd` to build its options.
  `import holidays` therefore sits inside `working_days`, with a one-line WHY
  comment:
  - it takes about **0.19 s**;
  - the `kohle-cli` import is about **0.9 s** today (both measured);
  - every command would otherwise pay that 20% to serve one.

  It is also never imported under `--period-end month-end`.

### 6.5 Dates verified against holidays 0.106 (for the tests)

| Case | Calendar last day | `last-working-day` (BY) |
|---|---|---|
| Saturday month end | 2026-10-31 (Sat) | 2026-10-30 (Fri) |
| BY holiday month end (Fronleichnam) | 2029-05-31 (Thu) | 2029-05-30 (Wed). **BE gives 2029-05-31**, which shows the state matters. |
| Weekend plus Karfreitag | 2024-03-31 (Sun) | 2024-03-28 (Thu) |
| December, 30th a weekday | 2026-12-31 | 2026-12-30 (Wed) |
| December, 30th a Saturday | 2028-12-31 | 2028-12-29 (Fri), the spec's example |
| December, 31st a Monday | 2029-12-31 | 2029-12-28 (Fri) |

---

## 7. Flags, not a persistent setting (decision 4, the spec's Open Question)

**Decision: flags only.**

- `--period-end month-end|last-working-day` defaults to `last-working-day`.
- `--state XX` defaults to `BY`.
- Both are on `net-worth-history`, defined beside it, because only one command
  uses them.

The reasons:

- **Every report input is in the database or on the command line.** The spec's
  determinism goal is "same ledger, same `prices`, same `today` → same output".
  - Today, a copy of `kohle.db` plus the command line reproduces any report.
  - A `KOHLE_STATE` environment variable would be invisible state outside both.
    Two terminals could print different histories from one database, and
    nothing on screen would say why.
  - `click.option(envvar=…)` makes that a one-line change, which is exactly why
    it is recorded and rejected rather than slipped in.
  - Environment variables are read today only by price plugins, for secrets.
- **A database setting is a feature of its own.** It needs:
  - a table and a migration, with a downgrade (`test_migration_downgrade`);
  - a setter command that writes through `crud_create`, so it is audited;
  - a precedence rule for when the flag disagrees with the setting.

  That is a configuration mechanism for one value, in a codebase that has
  declined one twice:
  - `settle-up`'s "a 'default cash account' setting would be a configuration
    mechanism this codebase does not have";
  - MV §8: "a threshold setting, a config file … not introduced".
- **The defaults already serve the user.** `BY` and `last-working-day` are the
  spec's defaults, so the everyday invocation is the bare
  `kohle-cli net-worth-history`. A user in another state writes one flag, or a
  shell alias.
- **The precedent holds.** `--max-age-days` is "the flag is the only knob".

**When to revisit.** Revisit when a second persistent preference appears, such
as a default staleness threshold or a base currency. A mechanism then pays for
itself across several values.

**The preferred form then.** A key/value `settings` table with an audited
setter, so the setting stays inside the database and keeps reports
reproducible from `kohle.db`. Environment variables remain rejected for the
reason above.

---

## 8. Shared row and valuation shape (decision 6)

### 8.1 `Position`

```python
@dataclass(frozen=True, slots=True)
class Position:
    holding: FifoHolding
    close: LatestClose          # never None: every positions row is nonzero and non-base

    @property
    def market_value(self) -> Decimal: ...       # _market_value(holding.quantity, close, holding.fifo_cost)

    @property
    def unrealised_gain(self) -> Decimal: ...    # market_value - holding.fifo_cost
```

- **It has the same shape as `ValuedBalance`:** a holding, plus its close.
- **`close` is not optional.** A positions row always looks up a close, because
  the row filter guarantees what `value_balances`' lookup condition tests: a
  nonzero quantity and a non-base unit.
  - So `QueryPositions` calls `latest_close(ctx, h.unit_id, today, N)` directly.
  - The lookup condition is still written once, in `value_balances`.
  - `latest_close` is still the only function that reads a close.
- **A `NoClose` row's gain is exactly 0.** Its `market_value` is
  `holding.fifo_cost`, so its `unrealised_gain` is `fifo_cost - fifo_cost`,
  which is `Decimal(0)` exactly.

### 8.2 One valuation rule, two cost bases

```python
def _market_value(quantity: Decimal, close: LatestClose | None, at_cost: Decimal) -> Decimal:
    # Fresh(c) | Stale(c): quantity * c.price;  NoClose(): at_cost;  None: quantity;  assert_never
```

| Row | Calls with | Cost basis on `NoClose` |
|---|---|---|
| `ValuedBalance.market_value` | `(balance.quantity, close, balance.at_cost)` | moving average |
| `Position.market_value` | `(holding.quantity, close, holding.fifo_cost)` | FIFO |

- **`ValuedBalance.market_value`'s body becomes the delegation.** Its behaviour
  is unchanged, and `test_valuation` pins it.
- **The rule has one copy and one `assert_never`.** So a fourth `LatestClose`
  variant (FX) fails mypy in one valuation place. MV's "the contract is the
  `LatestClose` union" holds.
- **Rejected: a `UnitBalance` built from FIFO data**, i.e.
  `average_cost = fifo_cost / quantity`. The quotient is inexact, so a `NoClose`
  gain would not be 0.

### 8.3 `ValuedRow = ValuedBalance | Position`

| Function | Was over | Now over |
|---|---|---|
| `at_market(rows)` | `Iterable[ValuedBalance]` | `Iterable[ValuedRow]` |
| `summarise(rows)` | `Iterable[ValuedBalance]` | `Iterable[ValuedRow]` |
| `_market_columns(row)` (cli) | `ValuedBalance` | `ValuedRow` |

- **Only the types widen.** Bodies and call sites are unchanged, because each
  function reads only `.close` and `.market_value`, which both rows have.
- **M is still "close is not None".** For positions every row has a close, so
  M is the row count, and S and C come from the types as before.
- **`positions` and `net-worth` share their status words, estimate line and
  four market columns.** This is through the same helpers, not copies, as the
  spec requires.
- **Why a union alias and not a `Protocol`.** There are exactly two row types and
  nothing anticipates a third. A union is how this codebase already names a
  closed set (`LatestClose`, `ValuationError`). A `Protocol` would be an
  abstraction with no second implementer waiting.
- **The two new totals.** `fifo_cost(positions)` and `unrealised_gain(positions)`
  are module functions in `reporting.py`, the siblings of `at_market`.
  - They sum the per-row figures, so "totals equal the sums of the rows" holds by
    construction.
  - `unrealised_gain(rows) == at_market(rows) - fifo_cost(rows)` exactly. The
    additions are exact at these magnitudes, and a test asserts it.
- **`QueryPositions` returns a bare `list[Position]`.** MV §4.5's reasoning for
  `balance` applies: one list, totals by function.

### 8.4 What extending `positions` to other units takes

**Commodities** (gold, say): `_replayed` becomes
`unit.kind in (UnitKind.security, UnitKind.commodity)`. Nothing else changes:

- the replay, `FifoHolding`, `Position`, `_market_value`, the totals and the
  rendering never name a kind;
- a commodity row values at its close when one is stored, or at its FIFO cost;
- its sales appear in `realised`, and its shortfalls fail like a security's.

That last point is intended: gold sold is a gain realised.

**"All non-base units"**: `_replayed` becomes
`unit.identifier != BASE_CURRENCY`.

- That filter must exclude the base currency, which is why the docstring on
  `_replayed` says so.
- It would put FX lots and FX realised gains into both reports, and FX is its
  own spec (`multi-currency-and-fx`). That is a decision for that spec, not a
  redesign.

**Splitting the filter.** If `positions` and `realised` ever want different
unit sets, the one filter splits into two at the same seam.

---

## 9. Use cases, transactions and `today`

```
QueryRealised.execute(year)                QueryPositions.execute(today, N)
  self._run -- one DbTransaction             self._run -- one DbTransaction
    replay_ledger(ctx)                         replay_ledger(ctx)
    filter by year                             latest_close(ctx, h.unit_id, today, N) per holding

NetWorthHistory.execute(start, end, mode, state, N)
  self._run -- one DbTransaction
    net_worth_lines(ctx)
    start := start, else the earliest loaded line's date, at most end
    dates := sample_dates(start, end, mode, state)
    aggregate_by_unit_through(own, dates), aggregate_by_unit_through(receivables, dates)
    valued_net_worth(ctx, NetWorthReport(o, r), d, N) per date
```

- **One `UnitOfWork` per report, reading only.** No `OperationGroup` is created,
  because groups appear only on the first write.
- **One session is not one snapshot** (MV §5). A concurrent `fetch-prices` can
  be seen part-way through a history. That is harmless, for the same reason MV
  gives.
- **`today` is read once, in the CLI.** It is read with
  `# noqa: DTZ011 - the user's local date, by design`, as the existing reports
  do.
  - `positions` passes it.
  - `net-worth-history` uses it only to default and validate `--to`. Below the
    CLI, every date is a parameter.
  - `realised` needs no date at all.
- **Defaults for the range:**
  - **`start`** defaults to the earliest `entry_date` among the loaded own and
    receivable lines, clamped to at most `end`.
    - An empty ledger gives `start = end`, which is one row dated `end`. When
      `end` is today, that equals `net-worth` on an empty ledger.
    - "Earliest ledger entry" is read as the earliest entry touching a
      balance-sheet account. Before that date, net worth is 0 by definition.
      The difference is only an entry touching income and expense alone, and it
      saves a query (§14.3).
  - **`end`** has no default below the CLI.
- **No defaults below the CLI.** `max_age_days`, `mode` and `state` are required
  on `execute`, as `max_age_days` already is on `ValuedNetWorth`.

---

## 10. CLI

### 10.1 `realised` (040)

```python
@click.option("--year", type=click.IntRange(min=1), default=None,
              help="Only sales dated in this year; their cost still comes from earlier lots")
```

**The rows:** `date`, `account`, `unit`, `quantity`, `proceeds`, `FIFO cost`,
`gain`, printed with `floatfmt=".2f", missingval="-"`.

**The empty case.** With no sales, `No sales` replaces the table (§14.4).

**The total.** `\nRealised gain: {realised_gain(sales):.2f}` always closes the
output.

```
date        account    unit            quantity    proceeds    FIFO cost    gain
----------  ---------  ------------  ----------  ----------  -----------  ------
2026-03-10  Depot      IE00B4L5Y983       15.00     1950.00      1600.00  350.00
2026-05-04  Broker     DE0005190003        5.00      375.00       400.00  -25.00

Realised gain: 325.00
```

### 10.2 `positions` (044)

`MAX_AGE_DAYS` is reused.

**The rows:**

```
unit, quantity, **_market_columns(p), "FIFO cost": p.holding.fifo_cost, "unrealised gain": p.unrealised_gain
```

**The empty case.** With no rows, `No positions` replaces the table (§14.4).

**Four lines always follow:**

- `\nMarket value: …`, the same label as `balance`'s market line, so one grep
  finds both;
- `FIFO cost: …`;
- `Unrealised gain: …`;
- `_estimates_line(summarise(positions))`.

```
unit            quantity    price  price date      market value  status                FIFO cost    unrealised gain
------------  ----------  -------  ------------  --------------  ------------------  -----------  -----------------
IE00B4L5Y983        5.00   112.40  2026-10-09            562.00  fresh                    600.00             -38.00
US0378331005        3.00   180.00  2026-09-01            540.00  stale (2026-09-01)       450.00              90.00
DE000A0F5UF5        4.00     -     -                     200.00  no price (at cost)       200.00               0.00

Market value: 1302.00
FIFO cost: 1250.00
Unrealised gain: 52.00
2 of 3 holdings estimated (1 stale, 1 at cost)
```

**Row order is the replay's first-seen unit order.** That is the same relative
order the units have in `net-worth`'s own section, so the two can be read side
by side.

### 10.3 `net-worth-history` (045, 046)

The options:

| Option | Type and default | Issue |
|---|---|---|
| `--from` (dest `start`) | `click.DateTime(formats=["%Y-%m-%d"])`, default `None` | 045 |
| `--to` (dest `end`) | the same type, default `None`, meaning today | 045 |
| `--period-end` | `click.Choice([p.value for p in PeriodEnd])`, default `last-working-day`, `show_default` | 046 |
| `--state` | `click.Choice(STATES)`, default `BY`, `show_default`; help says it is ignored with `month-end` | 046 |
| `MAX_AGE_DAYS` | as on `net-worth` | 045 |

**Why `--period-end` is a `Choice` of values.** click 8.3's enum support offers
member *names* (`month_end`), and the spec's spelling is the value
(`month-end`). `PeriodEnd(value)` converts it in the callback. Existing options
are `Choice`s over names because those names have no dashes.

**Validation happens before `make_session()` is called.** Each failure is a
`click.BadParameter`, so it exits with code 2:

- `--to` after today;
- `--from` later than the effective `--to`.

That second check covers "`--from` after today". An unknown `--state` or
`--period-end` is rejected by click before the callback runs at all.

**The rows:**

```
"date": r.on,
"at cost": r.report.at_cost.net_worth_at_cost,
"at market": r.report.net_worth_at_market,
"estimated": f"{e.estimated} of {e.holdings}"
```

where `e = r.report.estimates`.

No summary lines follow the table, because the spec asks for none.

An example, `--to 2026-10-12`: a past date that is not a sample date, so the
last row is dated `--to` and there is no today row.

```
date          at cost    at market  estimated
----------  ---------  -----------  -----------
2026-08-15   10210.00     10294.50  1 of 3
2026-08-31   12890.00     12961.20  1 of 3
2026-09-15   12650.00     12702.00  2 of 3
2026-09-30   15330.00     15391.10  1 of 3
2026-10-12   15105.00     15188.40  1 of 3
```

(All three examples were rendered with the installed tabulate 0.9.0 from
`Decimal`, `date` and `None` values. The numbers are illustrative.)

### 10.4 README

A new "Positions and profit" section after "Net worth" documents `positions`
and `realised`:

- **That FIFO runs per depot.**
- **That figures are gross.** They are before fees and tax, and serve as a
  cross-check against the broker, not a tax computation.
- **The spec's FIFO sentence:** `balance`'s `average cost` is a moving average,
  while `positions` and `realised` use FIFO.
- **How to record a move** (§3.3), and that a move realises nothing.
- **The three failures** and what each means.

A new "Net worth over time" section documents `net-worth-history`:

- the sample dates;
- `--period-end` and `--state`;
- that 24 and 31 December are never salary days;
- `--from`, `--to` and `--max-age-days`;
- that a date before price history began is valued at cost and marked.

---

## 11. Decimal handling and rounding

**MV §7 applies unchanged.**

- All arithmetic uses `Decimal` in the default context.
- Nothing is quantised in the use cases.
- Cells are formatted by tabulate's `.2f`, and totals use `Decimal`'s own
  `:.2f`.
- Totals equal the sums of the unrounded rows exactly. Printed cells may still
  differ from the printed total by a cent.

**Lot arithmetic is exact at ledger magnitudes:**

- splits are subtractions of 8-place quantities;
- costs are products of two 8-place values, at most 16 places;
- sums stay well inside 28 significant digits.

That exactness is what makes the testable equalities hold on `Decimal`s:

- FIFO cost of a buy-buy-sell;
- a `NoClose` gain of 0;
- `unrealised = market − FIFO`.

---

## 12. The decision categories

### State and data lifecycle

- **Every new report is a pure read.**
  - There is no write, so there is no `Operation` and no `OperationGroup`.
  - There is no plugin call.
  - Only stored closes are read.
- **The unit of success is the whole report.**
  - A lot inconsistency fails `positions` and `realised` entirely, before
    anything is printed: the use case returns `Err` before the CLI echoes.
  - A database error fails any of the three.
  - There is no partial table.
- **Missing data is not failure.** `NoClose` is a value with a fallback, as in
  MV.
- **Lots are derived, never stored** (a spec Non-Goal).
  - The replay is rebuilt from the ledger on every run, so there is no lot state
    to keep consistent across edits, adjusting entries or re-imports.
  - The replay's queues are local to one `replay` call and discarded with it.
- **Replayable.** The same database, the same flags, the same `today` and the
  same pinned `holidays` give the same output (§6.3).
- **Nothing is reversed or audited**, because nothing changes.

### Error propagation

```
services        AccountError | JournalError (partition, lines), PriceError (closes)
journal.py      balance_sheet_accounts: Err(AccountError); net_worth_lines: Err(BalanceError)
lots.replay     Err(LotError) -- pure; the first inconsistency in ledger order
lots use cases  Err(RealisedError = BalanceError | LotError)
reporting       Err(PositionsError = BalanceError | LotError | PriceError); history Err(ValuationError)
CLI             str(err) via ClickException, exit 1; flag and date errors exit 2 before any session
```

- **Representation changes in two places only:**
  - `replay` turns a queue state (a shortfall, a mixed entry) into a `LotError`
    that carries names and dates;
  - the CLI turns any `Err` into its `str`.
- **`replay` knows account names only through the maps it is handed.** It knows
  nothing of sessions.
- **The use case alone decides which lines are loaded and replayed.** It does so
  through the partition and the filter.
- **No error is raised.** `DbTransaction.execute`'s broad catch stays the only
  conversion of an unexpected exception (the AGENTS.md override).

### Concurrency and ownership

**Single-threaded, with no shared mutable state.**

- The CLI creates one session per command, and its `DbTransaction` owns and
  closes it.
- The replay's mutable queues are owned by one `replay` call.
- Everything returned is frozen dataclasses in lists built once and then only
  read.
- `holidays`' calendar object is built per report and is not shared. Its lazy
  year expansion mutates it internally, which is safe because nothing else holds
  it.
- A concurrent `fetch-prices` is visible mid-report, which is harmless (MV §5).

### Reuse

**Used rather than reimplemented:**

- from the market-value feature: `value_balances`, `ValuedNetWorthReport`,
  `at_market`, `summarise`, `_market_columns`, `_estimates_line`, `MAX_AGE_DAYS`,
  `ValuedBalance` (via `_market_value`) and `UnitBalance.unit_id`;
- from journal and prices: `latest_close`, `aggregate_by_unit`, `_RunningCost`
  and `NetWorthReport`;
- `account_lines_service` and its ordering;
- `net_worth`'s partition, now `balance_sheet_accounts`;
- `UnitOfWork._run` over `ctx` functions;
- the `date.today()`-once and `missingval` conventions;
- in tests: `_references`, the `forbidden_session_local` factory pattern, the
  monkeypatched `kohle.app.cli.cli.date` and the `people_root` fixture.

**Introduced and worth reusing next:**

- `balance_sheet_accounts`. Splitting has four hand-copies of the People-root
  plus descendants lookup, which could move onto it. That is a separate
  `change`, not this feature.
- `aggregate_by_unit_through`, for any report over time at cost.
- `valued_net_worth`, for any net worth as of a date.
- `replay_ledger` and `LotReplay`. A per-depot positions view would expose the
  queues from the same replay.
- `_market_value` and `ValuedRow`.
- `working_days`, for anything that needs a German banking day.

### Extension points

| Extension | Seam | Contract |
|---|---|---|
| Positions for commodities or other non-base units | `_replayed` | one predicate over `Unit`; nothing downstream names a kind (§8.4) |
| A different holiday source, or another country | `working_days` | returns `Callable[[date], bool]`; `period_end` and `sample_dates` take only that |
| Another period-end rule | `PeriodEnd` + the predicate choice in `sample_dates` | the rule is "last day of the month satisfying a predicate" |
| A persistent `--state` setting | the click option's default | §7: a DB setting, never an env var |
| FX or a fourth valuation outcome | `LatestClose` + `_market_value` | `assert_never` fails mypy in `_market_value` and `_market_columns` |
| Per-depot positions | `replay`'s queues | not exposed now; `LotReplay` would gain a field |
| TUI views | `QueryRealised`, `QueryPositions`, `NetWorthHistory` | types cross the boundary; the words live in the CLI and would move to `reporting.py` then (MV) |

There is **no plugin seam**. Reports never call plugins.

### Build vs. buy

| Component | Decision | Evaluated, and why not |
|---|---|---|
| FIFO lot replay | **build** (about 100 lines, pure) | **beancount** has FIFO booking, but over its own ledger model and parser; the whole ledger would have to be exported into it, and the account and People partition re-expressed there. **hledger / ledger-cli** are external processes with the same export problem. **pandas** (already a dependency) can match lots, but it is float-first, and a cumulative-sum lot matcher would hide the per-entry move rule that §3.3 must state exactly. None knows kohle's own-versus-People partition. |
| Public holidays per Bundesland | **buy**: `holidays==0.106` (spec-mandated) | **`dateutil.easter` plus a hand table** (dateutil is already installed) covers the moveable feasts, but would need per-state tables and their one-offs maintained by hand (BE Frauentag since 2019, TH Weltkindertag since 2019, the nationwide 2017 Reformationstag, BE's 2020 and 2025 one-offs). That is exactly what the package maintains. **`workalendar`** also has German states, but is less actively maintained and heavier. |
| Month arithmetic | stdlib `calendar.monthrange`, `timedelta` | `dateutil.relativedelta` is available, but not needed for "last day, step back". |
| Rendering | tabulate (already a dependency) | nothing new |
| Settings | none | §7 |
| Faster history close reads | **not built** | §5.5: linear, measured, one read path kept |

### Abstractions introduced

| Abstraction | Forcing problem |
|---|---|
| `kohle/use_cases/lots.py` | The replay must sit under the price-free guard, which `reporting.py` cannot. Nothing ties it to `journal.py` (§2.1). |
| `kohle/use_cases/sampling.py` | Confines `holidays` to one module and keeps the date rules pure and testable without a database (§6). |
| `BalanceSheetAccounts`, `balance_sheet_accounts` | `positions` must use net-worth's partition, and the replay needs the account names. One definition, three callers (§3.2). |
| `NetWorthLines`, `net_worth_lines` | History needs net-worth's two line sets loaded once. A tuple would let them transpose (§5.4). |
| `aggregate_by_unit_through`, `_unit_balances` | Per-date re-folding measured 4.64 s against 0.048 s (§5.4). One materialisation keeps the rows identical. |
| `valued_net_worth` | `ValuedNetWorth` and each history date need the same valuation in one transaction; the final row must equal `net-worth` by construction (§5.4). |
| `Lot` | A lot's date, order key and unit cost; splitting needs exact arithmetic (§4.2). |
| `Sale` | One `realised` row, crossing the session boundary with names, not ids (§4.2). |
| `FifoHolding` | Positions need per-unit FIFO quantity and cost with a `unit_id` for the close (§4.2). |
| `LotReplay` | One replay feeds both reports. Two lists of different types (§4.2). |
| `replay` | The rule of §3.3, pure, tested without a database. |
| `_take` | FIFO taking, used by sales, move-outs and dealing to receivers (§4.4). |
| `replay_ledger` | Partition, load, filter and replay, shared by `QueryRealised` and `QueryPositions` (§4.5). |
| `_replayed` | The one filter the spec allows to name a kind (§4.1). |
| `realised_gain`, `fifo_cost`, `unrealised_gain` | Totals live in the use-case layer, not the CLI (expense-splitting §9.3); each is the sum of rows (§8.3). |
| `Position` | A FIFO holding plus its close; `NoClose` must fall back to FIFO cost, not the moving average (§8.1). |
| `_market_value` | One valuation rule for two cost bases (§8.2). |
| `ValuedRow` | Two row types share the market total, estimate summary and column rendering (§8.3). |
| `HistoryRow` | Couples a sample date to its `ValuedNetWorthReport` (§5.4). |
| `QueryRealised`, `QueryPositions`, `NetWorthHistory` | One transaction per report, which only a `UnitOfWork` gives. |
| `LotError` and its three subclasses; `RealisedError`, `PositionsError` | The spec's fail-fast cases as values, and the use cases' `Err` types named for them. |
| `PeriodEnd`, `STATES` | The CLI's choices, and the value the use case receives (§6.1, §6.4). |
| `working_days` | The spec's "one small predicate"; the calendar is built once (§6.2). |
| `period_end`, `sample_dates` | The spec's sampling rule, pure (§6.1). |

**Explicitly not introduced:**

- **A stored lot table.** This is a spec Non-Goal.
- **A `Protocol` for valued rows.** A union suffices (§8.3).
- **A report wrapper around the `positions` or `realised` lists** (§4.5, §8.3).
- **A close-reader seam or a close cache** (§5.5).
- **A settings mechanism or environment variables** (§7).
- **A clock abstraction.** Dates are parameters, as in MV.
- **A kind parameter on the replay.** There is one filter, and a parameter would
  wait for a second caller that does not exist.
- **A per-depot breakdown in `LotReplay`.**

### Alternatives rejected

| Rejected | Where | Short reason |
|---|---|---|
| FIFO replay in `journal.py` | §2.1 | nothing forces it there; the module is recording code and already large |
| FIFO replay in `reporting.py` | §2.1 | that module imports prices, so the replay could never be guarded price-free |
| `QueryRealised` in `reporting.py` | §2.1 | would leave `realised`'s use case unguarded for no gain |
| Renaming `RECORDING_MODULES` / `_guarded_sources` | §2.2 | rewrites existing test identifiers for no behaviour change |
| `joinedload(JournalLine.account)` | §3.1 | a join on every fold to recover names the partition already loaded |
| Copying net-worth's partition into `lots.py` | §3.2 | two definitions of "own account" |
| Move = "every U-line on an own account" | §3.3 | misreads a mixed entry as a sale plus a fresh purchase |
| Partial moves read as "move the minimum, sell or buy the rest" | §3.3, §14.2 | which lots move and which sell is a guess |
| Recognising a move by description or a flag | §3.3 | the ledger has no such field; lines must say it |
| Keying queues by `unit_id` or grouping by `entry_id` | §4.3 | transient pure-test lines have neither populated |
| `Lot` storing total cost | §4.2 | splits need inexact division; a `NoClose` gain would not be 0 |
| A `deque` per queue | §4.4 | moved lots need sorted insertion; `insort` on a list is one rule |
| Separate own and People line loads for the replay | §4.5 | the lines of one entry would need merging back together |
| A kind filter in SQL | §4.5 | a new service parameter to save one report's hydration time |
| A sibling `close_on_or_before_service` | §5.1 | a second copy of one query |
| A history-only bounded reader beside `latest_close` | §5.2 | the final row would only *agree* with `net-worth`, not *be* it |
| `net_worth(ctx, as_of)` re-queried per date | §5.4 | about 5 queries and a full line hydration per sample |
| Re-folding each prefix with `aggregate_by_unit` | §5.4 | quadratic: 4.64 s on a ten-year ledger |
| Preloading closes for history | §5.5 | a second read path; linear cost accepted |
| `holidays.Germany.subdivisions` as the choice list | §6.4 | includes `Augsburg`, which is not a Bundesland |
| Importing `holidays` at module level | §6.4 | +0.19 s on every command |
| `click.Choice(PeriodEnd)` | §10.3 | offers names (`month_end`), not the spec's spelling |
| A `--state` env var (`envvar=`) | §7 | report input outside the database and the command line |
| A DB settings table now | §7 | a configuration mechanism for one value |
| A `Protocol` for valued rows | §8.3 | two closed types; a union is the house idiom |
| A `UnitBalance` built from FIFO data | §8.2 | an inexact `average_cost` quotient |
| `Position.close: LatestClose \| None` | §8.1 | admits a state the row filter rules out |
| Positions through `value_balances` | §8.1 | that function's input is `UnitBalance`, the moving-average fold |

---

## 13. Issue mapping and order

| Issue | Lands |
|---|---|
| 040 | **`journal.py`:** `BalanceSheetAccounts` and `balance_sheet_accounts`; `net_worth` on it. **`lots.py`:** `Lot`, `Sale`, `FifoHolding`, `LotReplay`, `_take`, `replay` (purchases and sales only), `replay_ledger` over **own** lines, `realised_gain`, `QueryRealised`, `_replayed`. **`domain_errors.py`:** `LotError` and `RealisedError`. **`cli.py`:** `realised_cmd` with `--year`. **Guards:** `lots.py` in `_guarded_sources` and `RECORDING_MODULES`; `lots.py` and `realised_cmd` in `_report_sources`; the new read-only test over `realised`. **README:** `realised`, gross, and moving average versus FIFO. |
| 041 | `LotShortfall`. The replay returns it when `_take` reports a shortfall, for a sale (and for a move-out once 042 exists). No CLI change: `Err` already exits 1 before any echo. |
| 042 | Move recognition (§3.3), pooled dealing in purchase order, and `UnbalancedOwnMove`. **README:** recording a move. Tests: two depots independent; A to B gives no row; B's later sale uses A's original lots in purchase order. This document is 042's "rule documented" criterion. |
| 043 | `replay_ledger` loads own **and** People lines; `SecurityMoveWithPeople`. **README:** the restriction. |
| 044 | **`reporting.py`:** `_market_value` (with `ValuedBalance.market_value` delegating), `Position`, `ValuedRow`, `fifo_cost`, `unrealised_gain` and `QueryPositions`; `at_market` and `summarise` typed over `ValuedRow`. **`domain_errors.py`:** `PositionsError`. **`cli.py`:** `positions_cmd`; `_market_columns` typed over `ValuedRow`. **Guards:** `positions_cmd` in `_report_sources`; `positions` added to the read-only test. **README:** `positions`. |
| 045 | **`price_services.py`:** the `on_or_before` bound. **`prices.py`:** `latest_close` bounded, with `today` renamed `as_of`. **`journal.py`:** `NetWorthLines`, `net_worth_lines`, `_unit_balances` and `aggregate_by_unit_through`. **`reporting.py`:** `valued_net_worth` (with `ValuedNetWorth` on it), `HistoryRow` and `NetWorthHistory`, with `value_balances`' `today` renamed `as_of`. **`sampling.py`:** `period_end` and `sample_dates(start, end)` at calendar month-end. **`cli.py`:** `net_worth_history_cmd` with `--from`, `--to` and `MAX_AGE_DAYS`. **Guards:** callback and read-only test. **README.** |
| 046 | `holidays==0.106` with `uv lock`. **`sampling.py`:** `PeriodEnd`, `STATES` and `working_days`, and `sample_dates` gains `mode` and `state`. `NetWorthHistory.execute` gains `mode` and `state`. **`cli.py`:** `--period-end` (default `last-working-day`) and `--state` (default `BY`). The `STATES` contract test. **README:** both flags. |

**Order: 040 → 041 → 042 → 043 → 044, then 045 → 046.**

- **The two chains are independent in substance.** 045 declares no dependency,
  but both chains edit `cli.py`, `reporting.py`, the README and the guard file.
  Landing them in sequence avoids rebasing one onto the other.
- **044 last in the first chain.** It needs 042 and 043, so that `positions`
  fails exactly as `realised` does.
- **046's default flips 045's behaviour.** It changes the default period end
  from month-end to last-working-day. 045's tests should pass `month-end`
  explicitly once 046 lands, or be written against `sample_dates` at the
  use-case level with the mode given. They are not "existing tests" in the
  spec's sense, because they belong to this feature. Their edit in 046 is
  expected, and should be said in 046's commit.

**Scaffolding forced by the issue boundaries.** There are three cases:

1. **040 ignores the shortfall `_take` returns.** A sale beyond the queue costs
   only what was there. 041 replaces that with the `Err`. `_take` returns the
   shortfall from 040 onwards, so 041 changes only its caller.
2. **Until 042, an own-depot move reads as a sale from A plus a purchase into
   B.** The §3.3 table loses its "move" row, so no code is removed, but 042
   changes what such an entry produces.
3. **Until 043, `replay_ledger` loads own lines only.** A People line in a
   security is invisible, so a move to a person reads as a sale. 043 widens the
   load to own ∪ People and adds the check.

**After landing.** `AGENTS.md`'s Context should gain one sentence. It is not
edited by this design; the user edits it. The sentence: FIFO lives in
`kohle/use_cases/lots.py`, which a test keeps price-free, so realised gain
depends only on recorded prices. Without it, a later agent reading "price-reading
reports go in reporting.py" might move the replay there.

---

## 14. Gaps in the spec, and points for the user

1. **Future-dated entries break the "final row equals `net-worth`" rule.**
   - `net-worth` folds every line, whatever its date (`account_lines_service`
     has no date filter).
   - `net-worth-history`'s row for today folds lines dated on or before today,
     as the spec defines.
   - A ledger holding an entry dated after today (a scheduled transfer recorded
     ahead) therefore makes the two differ, and the spec's testable equality
     would fail on it.
   - **The design follows the per-D definition.** The equality test uses a
     ledger with no future-dated entry.
   - **The user should decide one of three things:**
     - accept the difference;
     - make `net-worth` exclude lines after today, which the spec forbids as a
       change to `net-worth`;
     - make the final row include them, which contradicts "lines dated on or
       before D".
2. **Unequal own-depot moves are a third fail-fast case the spec does not list.**
   - **The case:** an entry that credits a security out of own depots and
     debits it into own depots in *different* quantities.
   - **What the design does:** fails with `UnbalancedOwnMove` (§3.3).
   - **Why:** the spec names two failures, and recognising a move was left to
     the design. Any non-failing reading would guess which lots moved and which
     were sold.
   - **The user should confirm, or choose a different rule.**
3. **Default range edges.**
   - **What the spec says:** "earliest ledger entry date to today".
   - **What it leaves open:**
     - an empty ledger;
     - a ledger whose earliest entry is after an explicit past `--to`;
     - an entry that touches no balance-sheet account.
   - **What the design does** (§9):
     - takes the earliest entry among own and receivable lines;
     - clamps `start` to at most `end`;
     - gives one row dated `end` when the ledger is empty.

     None of these can change a figure. Before the first balance-sheet line,
     net worth is 0.
4. **Empty `positions` and `realised` output.**
   - **What the spec leaves open:** what prints when there are no rows.
   - **What the design does:**
     - prints `No positions` or `No sales` in place of the table, where
       tabulate would print nothing;
     - still prints the closing lines that the spec says always follow:
       `Realised gain: 0.00`, or the three zero totals plus
       `0 of 0 holdings estimated`.
   - **If the user prefers `balance`'s style** (message only, no zero lines, as
     decided in MV §10.4), that is a one-line change per command.
5. **`--state` accepts the 16 Bundesländer, not everything `holidays` knows.**
   - `holidays` 0.106 also offers `Augsburg` as a German subdivision.
   - The spec says Bundesland, so it is rejected (§6.4).
   - Augsburg's only extra holiday, 8 August, can never be a period end anyway.
6. **Observation, not a gap: moves shift `net-worth`'s at-cost total.**
   - The moving-average fold that `net-worth`'s at-cost total uses (unchanged
     here) treats a move's receiving line as a purchase at the move's recorded
     price.
   - So a move recorded at any price other than the running average changes
     `Net worth (at cost)` and the receiving account's `balance` average cost.
   - `positions`' FIFO cost is unaffected, so after such a move `positions` and
     `net-worth` disagree on cost.
   - The README's "moving average versus FIFO" sentence covers it in general. A
     README hint to record moves at the current average cost would keep the two
     closer, though never equal across several lots.
   - This is pre-existing behaviour of the fold. Changing it is outside this
     spec.

---

## 15. Testing notes

This extends the existing layers:

- pure functions, with no fixture;
- use cases against `session`, with the `people_root` fixture;
- the CLI through `CliRunner` with `session_factory`;
- the guards.

Ledgers are built with `add_journal_entry_service`, as in `test_reporting.py`.
Closes are seeded with `session.add(Price(...))`.

**Pure (`replay`, with transient lines whose `entry=JournalEntry(id=…, entry_date=…)` and `id=` are set):**

- **Buy, buy, sell.** Buy 10 @ 100 (d1), buy 10 @ 120 (d2), sell 15 @ 130 (d3).
  - The sale has proceeds 1950, FIFO cost 1600 and gain 350.
  - The holding left is 5 at a cost of 600.
- **Two depots replay independently.** A buys 10 @ 100, B buys 10 @ 200, A
  sells 5 @ 150.
  - The sale's FIFO cost is 500.
  - B's holding is unchanged.
- **A move carries the original lots, in purchase order.**
  - A buys 5 @ 100 (d1) and 5 @ 110 (d2). B buys 5 @ 120 (d3). Then A moves 10
    to B (d4), and B sells 12 @ 130 (d5).
  - The move produces no `Sale`.
  - B's sale costs 500 + 550 + 240 = 1290, and its gain is 270. A's d1 and d2
    lots precede B's own d3 lot.
- **Shortfalls name their case.**
  - Buy 5, sell 7: `LotShortfall` with shortfall 2, naming the unit, account
    and date.
  - A move-out beyond the queue gives the same.
- **People lines fail whichever way they move.**
  - `Depot cr X` with `Alice dr X` gives `SecurityMoveWithPeople`, and so does
    the reverse.
  - `Depot cr X` with `Alice dr EUR` is a sale.
  - `Alice dr X` with `Bob cr X` is ignored.
- **An unbalanced move fails.** `A cr X 10` with `B dr X 6` gives
  `UnbalancedOwnMove`.
- **The rest of the pure layer:**
  - `realised_gain` of an empty list is 0.
  - `_take` splits a lot exactly, and the sum of the taken parts plus the
    remainder equals the original.

**Pure (`journal.py`):**

- `aggregate_by_unit_through(lines, dates)` gives
  `[aggregate_by_unit(prefix(d)) for d in dates]` on a mixed ledger, compared
  with `==`.
- A date before the first line gives `[]`.

**Pure (`sampling.py`):**

- **`period_end` with fake predicates:**
  - always-true gives the calendar last day;
  - a predicate rejecting the last two days steps back two.
- **`sample_dates` at month-end:**
  - a range across a year boundary gives the 15th and the last day of each
    month;
  - `--to` mid-month appends `--to`;
  - `--to` on the 15th or on a period end appends nothing;
  - a `start` after the 15th drops that 15th.
- **`working_days("BY")` and `sample_dates` under `last-working-day`, real
  calendar:** every row of §6.5. Also:
  - 24 and 31 December are never returned for any month in a multi-year range;
  - 2029-05 differs between BY and BE.
- **The `STATES` contract.** `holidays.country_holidays("DE", subdiv=s)` raises
  for no `s` in `STATES`, and `"Augsburg"` is not in `STATES`.

**Pure (`reporting.py`):**

- `Position.market_value` under `Fresh` and `Stale` is quantity × close.
- Under `NoClose` it is `fifo_cost`, and `unrealised_gain == 0`.
- `fifo_cost`, `unrealised_gain` and `at_market` over positions satisfy
  `unrealised = market − FIFO` exactly.
- `summarise` over positions counts M as the number of rows.

**Use case (`session`, pinned dates):**

- **`QueryRealised`:**
  - `year=2026` lists only that year's sales, whose cost uses 2025 lots;
  - `year=None` lists all sales;
  - the People subtree is excluded;
  - an unknown People root gives `AccountNotFoundError` (the inherited
    behaviour, pinned).
- **`QueryPositions`:**
  - quantities are summed across two depots;
  - it gives `Fresh`, `Stale` and `NoClose` rows;
  - a sold-out security has no row;
  - a shortfall is an `Err`.
- **`latest_close` and `value_balances` respect `as_of`:**
  - with closes on d-10 and d+5, `as_of=d` returns the d-10 close, as `Stale`
    under N = 7;
  - `as_of` before the first close gives `NoClose`.
- **`NetWorthHistory`:**
  - a line dated on a sample date is included, and the next day's is excluded;
  - the D before price history is at cost and marked;
  - the last row with `end=TODAY` equals `ValuedNetWorth.execute(TODAY, N)` in
    `at_cost.net_worth_at_cost`, `net_worth_at_market` and `estimates`, on the
    MV mixed ledger.

**CLI:**

- **`realised`:**
  - the header tokens;
  - each row's last token is its gain;
  - `Realised gain: X` is the last line;
  - a shortfall exits 1 with the unit, account, date and shortfall in the
    output and no header line;
  - a People move exits 1 naming the entry id.
- **`positions`:**
  - the header tokens;
  - the four closing lines, with totals equal to the sums on fixtures exact to
    2 places (MV §10.11);
  - a `no price (at cost)` row with gain `0.00`;
  - the same failures as `realised`.
- **`net-worth-history`, run with `--period-end month-end` unless the test is
  about the default:**
  - `--to` a past non-sample date ends with that row and has no today row;
  - `--to` tomorrow, and `--from` after `--to`, exit 2 with a factory that fails
    if called;
  - `--state XX` exits 2 the same way;
  - with `--to` omitted, the last row matches `net-worth`'s at-cost and
    at-market lines and the K and M of its estimates line on the same ledger.
    Both commands read `date.today()`; pin it by monkeypatching
    `kohle.app.cli.cli.date` (MV §10.7) so a midnight rollover cannot split
    them.
- **Status cells contain spaces.** Assert them by substring within a row, not by
  token position (MV §11).

**Guards (`tests/test_price_guards.py`):**

- **Static.** §2.2's three extensions, which are new parametrised cases only.
- **Behaviour.** A new test leaves the existing
  `test_reports_leave_prices_and_operations_untouched` untouched, because it
  does not count groups.
  - Ledger: a buy, a sale and one stored close.
  - Count the `prices`, `operations` and `operation_groups` rows.
  - Run each new command through `CliRunner`: `realised` (040), `positions`
    (044) and `net-worth-history --from <first entry>` (045).
  - Assert the three counts are unchanged.
- **Transitive.** `import kohle.use_cases.lots` loads no price module, as part
  of `RECORDING_MODULES`.

**Existing tests stay unchanged.** The regression net is:

- `test_reporting`;
- `test_valuation`, which pins `ValuedBalance.market_value` through the
  delegation;
- `test_latest_close`, which passes `as_of` positionally, with no close after it;
- `test_net_worth`, which pins the `net_worth` refactor;
- `test_average_cost`, which pins the `_unit_balances` extraction;
- `test_market_value_cli`;
- the existing guard cases.
