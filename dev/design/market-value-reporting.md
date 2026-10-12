# Design: Market value reporting

Spec: `dev/specs/market-value-reporting.md` (frozen)
Issues: `dev/issues/035`–`039`

> **Status: revised for the re-frozen spec.** After the first pass, the user
> decided that `balance` prints `Market value: X` and the estimate summary
> only when M > 0. A euro-only account, such as an expense category, prints
> neither line, so its output differs from today only by the new columns.
> `net-worth` always prints both. This settles §10.4; the rendering is in
> §6.3. The spec and issues 035, 037, 038 and 039 have also adopted §10.1–3,
> §10.5–7 and §10.11.

Layering per `AGENTS.md` stays `app -> use_cases -> services ->
infrastructure/domain`. Only services touch a `Session`. Functions return
`Result[T, E]`; domain errors are `Exception` subclasses used as values.

---

## 1. Summary of the shape

| File | Change | Issue |
|---|---|---|
| `kohle/use_cases/journal.py` | `UnitBalance` gains a `unit_id` field (§3) and an `at_cost` property (§4.2). `aggregate_by_unit` records the id. `_at_cost` sums `at_cost`. `net_worth(ctx)` is factored out of `NetWorth`, which becomes `self._run(net_worth)` (§2.4). Nothing here names a price. | 035 |
| `kohle/use_cases/reporting.py` | **new**. 035: `ValuedBalance`, `value_balances`, `at_market`, `ValuedNetWorthReport`, `ValuedNetWorth`. 036: `EstimateSummary`, `summarise`, `ValuedNetWorthReport.estimates`. 038: `QueryValuedBalance`. | 035, 036, 038 |
| `kohle/domain/domain_errors.py` | `ValuationError = BalanceError \| PriceError` | 035 |
| `kohle/app/cli/cli.py` | 035: `net-worth` runs on `ValuedNetWorth`, gains `_market_columns`, `missingval="-"` and the market line. 036: `_estimates_line`. 037: the `MAX_AGE_DAYS` option on `net-worth`. 038: `balance` runs on `QueryValuedBalance`, uses the same helpers and option, and prints its two lines only when M > 0. | 035–038 |
| `tests/test_price_guards.py` | the read-only guards (§9, 039) | 039 |
| `README.md` | "Net worth" (035–037) and "Reading the ledger" (038) | 035–038 |

No schema change, no migration, no new dependency.

**Import direction.** `reporting.py` imports from `journal.py` and
`prices.py`. `prices.py` already imports from `journal.py`. Only `cli.py`
imports `reporting.py`. The graph is acyclic: `cli → reporting → prices →
journal`, plus `reporting → journal`. `journal.py`, `classification.py` and
`splitting.py` must never import `reporting.py`. The existing transitive guard
(`test_recording_use_cases_do_not_transitively_import_price_modules`) already
enforces that, because importing `reporting` loads `kohle.use_cases.prices`.

---

## 2. Where valuation lives (decision 1)

### 2.1 A new module: `kohle/use_cases/reporting.py`

- **`journal.py` is ruled out** by `tests/test_price_guards.py`, as the spec
  says. It may not name `Price` or import a price module, even transitively.
- **`prices.py` is ruled out by issue 039.** It holds `AppendPrices` and
  imports `add_price_service`. With valuation in the same module, a static
  check that "report code names no price writer" could not be written: the
  module that reads closes for reports would also be the module that writes
  them. Keeping them apart also means a reporting change never touches the
  fetcher's module.
- **The name is `reporting.py`.** `cli-record-and-balances.md` §1 and
  `expense-splitting.md` §9.1 both named it as the read side's eventual home.
  Everything still deferred in `portfolio-and-profit-reporting` reads prices:
  a positions view, unrealised gain, net worth over time. By the same guard,
  all of it has to sit outside `journal.py`, so it lands here too.

### 2.2 Composition in the CLI: rejected

The CLI holds no `DbTransactionContext`, so it can only compose use cases.
To value balances in the CLI it would have to run `QueryAccountBalance` and
then a second `UnitOfWork` that reads closes. That is two transactions, which
breaks the spec's "all the `latest_close` reads for one report happen inside a
single `UnitOfWork` … alongside the balance fold". It would also put the
valuation rule in one frontend. That is the reason `call_price_plugins` sits
in `use_cases` and not in `fetch_prices_cmd` (price-fetcher §6.1, §14.5).

### 2.3 `QueryAccountBalance` and `NetWorth` stay where they are

Neither moves, and neither changes signature.

- **The tests pin them.**
  - `test_balance_services`, `test_cash_envelope_scenario`,
    `test_classification_scenario`, `test_splitting_scenario`,
    `test_broker_import_scenario` and `test_reclassify` import
    `QueryAccountBalance` from `kohle.use_cases.journal` and use it as their
    ledger oracle.
  - `test_net_worth` imports `NetWorth` from there and calls `.execute()`
    with no arguments.

  The spec requires every existing balance and net-worth test to pass
  unchanged.
- **Re-exporting is impossible.** If `journal.py` re-exported anything from
  `reporting.py`, it would import `prices` transitively and fail the guard.
- **Adding `today` / `max_age_days` to them is impossible for the same
  reason.** They live in `journal.py` and cannot read a close.

**Consequence, recorded so it is not mistaken for dead code.** After 035 the
CLI no longer calls `NetWorth`, and after 038 it no longer calls
`QueryAccountBalance`. Both remain the at-cost read use cases that the test
suite reads the ledger through. Deleting them is a separate `change` that
would have to move that oracle in seven test files. It is not this feature.

**The split point from `expense-splitting.md` §9.1 moves, but only partly.**
The guard forces a second module for reports that read prices, so it moves
the point at which reads are split. It does not move the fold. These stay in
`journal.py` permanently:

- `aggregate_by_unit`;
- `account_balance`;
- `held_units`;
- `net_worth` (new).

The reason is that `splitting.py`, which is under the guard, imports the
first two, and `prices.py` imports `held_units`. If FIFO later triggers the
move of the at-cost use cases (`QueryJournalByPeriod`, `QueryAccountBalance`,
`NetWorth`), `reporting.py` is where they go. The functions they call stay
behind.

### 2.4 `net_worth(ctx)` is factored out of `NetWorth`

```python
def net_worth(ctx: DbTransactionContext) -> Result[NetWorthReport, BalanceError]
```

- **Why it is needed.** `ValuedNetWorth` needs exactly the partition that
  `NetWorth` computes: People root, descendants, balance-sheet ids, two line
  loads and two folds. It needs it inside its own transaction, and one
  `UnitOfWork` cannot call another (`RecordSimpleEntry`'s docstring).
  Copying 25 lines would give net worth two definitions.
- **It follows the house pattern.** This is the same move
  `account_balance(ctx, id)` made for `WhoOwesWhat` (expense-splitting §7.1,
  §9.2). `NetWorth.execute` becomes `return self._run(net_worth)`, as
  `WhoOwesWhat.execute` is `self._run(_person_balances)`. The name is public
  because another module calls it.
- **A docstring is updated.** `NetWorth`'s sentence "Market valuation is a
  separate, deferred spec (design §9.4)" now points at
  `reporting.ValuedNetWorth`.

`QueryAccountBalance`'s closure is **not** factored. It is two calls, a name
lookup and `account_balance`, and `QueryValuedBalance` repeats them. That is
the same composition `WhoOwesWhat` does, not a second copy of a rule.

### 2.5 The guard after this feature

- **`journal.py` stays clean.** Its changes are an `int` field, a `Decimal`
  property and an extracted function. None of them names `Price`,
  `PriceBinding`, `PriceFetcherPlugin` or a price module.
- **`reporting.py` is not added to `RECORDING_MODULES`.** It exists to read
  prices.
- **039 adds the opposite guard:** report code names no price writer (§9).

---

## 3. How the unit id reaches `latest_close` (decision 2)

**Carry it on `UnitBalance`.**

```python
@dataclass(frozen=True, slots=True)
class UnitBalance:
    unit_identifier: str
    quantity: Decimal
    average_cost: Decimal | None
    unit_id: int

    @property
    def at_cost(self) -> Decimal: ...   # §4.2
```

- **The fold already has the id.** Every `JournalLine` carries `unit_id`.
  Resolving the identifier again through `get_unit_by_identifier_service`
  would spend a query to recover what the fold had just discarded.
- **Resolving would widen the error type for no real case.** It costs one
  query per valued row, and it adds `UnitError` (`UnitNotFoundError`) to the
  report's error type. That error cannot occur: the identifier was read, in
  the same session, from a line's own unit, and units are never deleted.
- **Services key by id** (price-fetcher §8). Price-fetcher's Extension points
  left this choice to reporting, and expense-splitting §9.4 named
  `UnitBalance` as "the contract between the fold and its presenters".
  Widening that contract is the intended seam.
- **Effect on existing code was checked.**
  - There is one construction site, `aggregate_by_unit`.
  - No test constructs a `UnitBalance`.
  - No test compares one by equality. Tests read fields, or compare
    `balances == []`.
  - `WhoOwesWhat`, `SettleUp`, `held_units` and `who-owes-what` ignore the
    new field.
  - The field goes **last**, so the first three keep their positional
    meaning.
- **Where the id comes from.** It is `line.unit_id`, recorded the first time
  the fold sees an identifier. The fold still groups by identifier. Grouping
  by id would change the key underneath the pure fold tests.
- **The pure fold tests will carry `None`.** `test_average_cost.py` builds
  transient `JournalLine(unit=Unit(...))` objects with no ids, so its
  `UnitBalance`s will hold `unit_id=None`. Those tests read only quantity and
  average cost, and they pass unchanged. The `None` never reaches
  `latest_close`, because nothing in those tests values a balance. This is
  recorded so nobody "fixes" it by making the field `int | None`.

---

## 4. The valuation (decision 3)

### 4.1 `ValuedBalance`: the rule, pure

```python
@dataclass(frozen=True, slots=True)
class ValuedBalance:
    balance: UnitBalance
    close: LatestClose | None    # None: no close was looked up

    @property
    def market_value(self) -> Decimal: ...
```

| `close` | `market_value` |
|---|---|
| `Fresh(c)`, `Stale(c)` | `balance.quantity * c.price` |
| `NoClose()` | `balance.at_cost`, i.e. quantity × average cost (§4.2) |
| `None` | `balance.quantity`. A base-currency row is × 1, and a zero-quantity row is 0 either way. |

The `match` ends in `assert_never`, as `_fetch_row` does.

- **Pure, and tested without a database.** The tests build a `UnitBalance`
  and a transient `Price(...)`, as `test_latest_close` does before it adds
  one, and read `market_value`. Balance and net worth both reach the rule
  only through this property. There is no second copy.
- **A wrapper, because the guard forces one.** A `LatestClose`-typed field on
  `UnitBalance` would make `journal.py` import `prices`.
- **`close: LatestClose | None`, not a close plus a base-currency flag.**
  - The spec's three outcomes are already a union that mypy makes exhaustive
    (price-fetcher §8).
  - A separate `is_base` flag plus an optional close admits two invalid
    combinations: a base row with a close, and a non-base row without one.
  - Folding "not looked up" into `None` leaves one constructible invalid
    state: a nonzero non-base row with `None`. The only production
    constructor, `value_balances` (§4.3), writes the lookup condition once.
- **Neither the status word nor the price is stored.** Both are read off
  `close` at render time (§6.1).

### 4.2 `UnitBalance.at_cost`: one per-row cost figure

The property is `quantity * average_cost`, or `Decimal(0)` when
`average_cost` is `None`. That is only ever the case when quantity is 0.

- **The expression already exists twice.** `_at_cost` skips `None`, and
  `_net_worth_rows` in the CLI writes `else Decimal(0)`.
- **The spec would force a third copy.** It says the `NoClose` fallback
  "reuses exactly that per-row figure".
- **One property now has three readers:**
  - `_at_cost`, which sums it;
  - the net-worth `at cost` column;
  - the `NoClose` arm of `market_value`.
- **mypy gets one `None` branch.** Without the property, the `NoClose` arm
  would need a `None` branch for an `average_cost` that cannot be `None`
  there.
- **The docstring moves to the property.** `_at_cost`'s docstring (the
  `sum(line.value)` trap, expense-splitting §9.3) moves with the formula.
  `_at_cost` keeps a pointer to it.
- **The at-cost figures do not change.** A zero row's `Decimal(0)` adds
  exactly 0, so `own_at_cost`, `receivables_at_cost` and `net_worth_at_cost`
  are unchanged. `tests/test_net_worth.py` passes as is.

### 4.3 `value_balances`: the only place a close is read

```python
def value_balances(
    ctx: DbTransactionContext,
    balances: Iterable[UnitBalance],
    today: date,
    max_age_days: int,
) -> Result[list[ValuedBalance], PriceError]
```

- **When a close is read.** A balance gets
  `latest_close(ctx, b.unit_id, today, max_age_days)` exactly when
  `b.quantity != 0 and b.unit_identifier != BASE_CURRENCY`. Every other
  balance gets `close=None`. This is the only place in the feature that
  reads a price, and the only place that condition is written.
- **Base currency is detected by identifier**, as `balance_cmd`'s restatement
  row and `validate_close` already do.
- **The input order is kept**, which is the fold's first-seen order. The
  existing row order does not change.
- **Non-security units are looked up too**, and come back `NoClose`. The spec
  says never-fetched, unbound and non-security units "are not told apart".
  Skipping the lookup for them would need `kind` on `UnitBalance`, and
  would buy nothing but one indexed query per currency or commodity row.
- **One read per unit per section.** Within a section, `aggregate_by_unit`
  has already folded every account into one row per unit, so the spec's "one
  `latest_close` read, applied to the summed quantity" holds by
  construction.
- **A failed read ends the loop with `Err`.** See Error propagation.

### 4.4 The market total and the estimate summary

```python
def at_market(rows: Iterable[ValuedBalance]) -> Decimal    # sum of market_value, the mirror of _at_cost


@dataclass(frozen=True, slots=True)
class EstimateSummary:
    holdings: int    # M
    stale: int       # S
    no_price: int    # C

    @property
    def estimated(self) -> int: ...    # K = S + C


def summarise(rows: Iterable[ValuedBalance]) -> EstimateSummary
```

- **M counts `close is not None`.** That is the lookup condition from §4.3,
  so M is, by construction, the spec's "non-base-currency rows with nonzero
  quantity". One condition serves both purposes.
- **`holdings` (M) also decides whether `balance` prints its two lines**
  (§6.3). No second definition of M is written for that.
- **S and C come from the types.** They count `isinstance(close, Stale)` and
  `isinstance(close, NoClose)`, never the rendered strings.
- **The counts are of rows.** In net worth, a unit present in both sections
  is two rows and counts twice. The spec's definitions are per row.
- **The field is `no_price`, not `at_cost`.** `at_cost` already names a
  `Decimal` figure everywhere in this codebase.
- **Pure.** `summarise` and `at_market` are tested on hand-built rows.

### 4.5 Report types and use cases

```python
@dataclass(frozen=True, slots=True)
class ValuedNetWorthReport:
    at_cost: NetWorthReport
    own: list[ValuedBalance]
    receivables: list[ValuedBalance]

    @property
    def net_worth_at_market(self) -> Decimal: ...     # at_market(own) + at_market(receivables)

    @property
    def estimates(self) -> EstimateSummary: ...       # summarise over both sections (036)


class ValuedNetWorth(UnitOfWork[ValuedNetWorthReport, ValuationError]):
    def execute(self, today: date, max_age_days: int) -> Result[ValuedNetWorthReport, ValuationError]: ...


class QueryValuedBalance(UnitOfWork[list[ValuedBalance], ValuationError]):
    def execute(
        self, account_name: str, today: date, max_age_days: int
    ) -> Result[list[ValuedBalance], ValuationError]: ...
```

- **It holds the unchanged `NetWorthReport`.** `Net worth (at cost): X` is
  then printed from the same property it is printed from today, so it is
  byte-identical by construction rather than by re-derivation. The
  `UnitBalance`s appear twice, inside `at_cost` and inside the valued rows.
  They are the same immutable objects, which is accepted.
- **The "both sections" rule lives on the type**, as `net_worth_at_cost`
  does. Expense-splitting §9.3 says a ledger total is not computed in the
  CLI.
- **`balance` returns a bare `list[ValuedBalance]`.** Its whole report is one
  list, so the CLI calls `at_market` and `summarise` on it directly. It reads
  `summary.holdings` to decide whether to print (§6.3). A wrapper type around
  one list has no forcing problem.

---

## 5. One transaction per report; `today` and `max_age_days` (decision 4)

```
ValuedNetWorth.execute(today, N)                 QueryValuedBalance.execute(name, today, N)
  self._run(use_case)  -- one DbTransaction        self._run(use_case)  -- one DbTransaction
    net_worth(ctx)                                   get_account_by_name_service(ctx, name)
    value_balances(ctx, own, today, N)               account_balance(ctx, account.id)
    value_balances(ctx, receivables, today, N)       value_balances(ctx, balances, today, N)
```

- **One session for the whole report.** The fold and every `latest_close`
  read run in the closure passed to `self._run`: one `DbTransaction`, one
  session, closed at the end. This is the shape price-fetcher §8 built
  `latest_close` for: a `ctx` function, because a nested `UnitOfWork` would
  close the session.
- **No writes, so no `OperationGroup`.** `DbTransactionContext` creates the
  group lazily on the first write, and the commit carries nothing. Issue 039
  pins this.
- **A caveat, verified.** One `UnitOfWork` is one session, not one snapshot.
  pysqlite's legacy transaction control does not `BEGIN` before a `SELECT`.
  A probe confirmed that a second session's committed insert is visible to a
  still-open read-only session. So a `fetch-prices` that commits between the
  fold and a close read is visible mid-report.
  - That is harmless. Each close read is a true stored fact, and a unit is
    valued by whichever close was latest when it was read.
  - It is not guarded, for the same reason price-fetcher §12 does not guard
    concurrent runs: this is a single-user CLI.
- **`today` is read once.** The CLI callback calls `date.today()` once per
  command, with the same `# noqa: DTZ011 - the user's local date, by design`
  as `fetch_prices_cmd`. The value goes through `execute` and
  `value_balances` into `latest_close`. Nothing below the CLI reads a clock,
  and every row of one report shares one `today`.
- **`max_age_days` has no default below the CLI.** It is a required
  parameter on both `execute`s and on `value_balances`.
  - After 037, two defaults of 7 exist. One is `latest_close`'s own
    `max_age_days: int = 7` (price-fetcher §8), which `test_latest_close`
    relies on. The other is the flag's `default=7`.
  - Reporting always passes the value explicitly. So the flag governs
    reports, and `latest_close`'s default governs only direct callers.
  - Unifying them into a constant would reopen price-fetcher §8's "the
    default sits in the signature", and would remove only a literal.
- **035 needs scaffolding until 037.** In 035, before the flag exists,
  `net_worth_cmd` passes the literal `7` (§9).

---

## 6. CLI rendering (decision 5)

### 6.1 The four columns, rendered once

`_market_columns(row: ValuedBalance) -> dict[str, object]` returns these
keys, in this order:

| `row.close` | `price` | `price date` | `market value` | `status` |
|---|---|---|---|---|
| `Fresh(c)` | `c.price` | `c.price_date` | `row.market_value` | `"fresh"` |
| `Stale(c)` | `c.price` | `c.price_date` | `row.market_value` | `f"stale ({c.price_date.isoformat()})"` |
| `NoClose()` | `None` | `None` | `row.market_value` | `"no price (at cost)"` |
| `None` | `None` | `None` | `row.market_value` | `None` |

The `match` ends in `assert_never`.

- **The status words live in the CLI**, as `_fetch_row`'s outcome words do
  (price-fetcher §6.7). The use case returns types, and the words are
  presentation. One helper renders both commands, so there is one copy of
  the vocabulary. If the TUI ever shows these views, the helper moves to
  `reporting.py` then (Extension points).
- **A `NoClose` row shows `-` for price, not the average cost.** The price
  column means "the close". The status already says `at cost`, the market
  value column carries the figure, and `balance` shows average cost in its
  last column anyway.
- **Only column attributes of the `Price` are read outside the session.**
  `price` and `price_date` are fine. `close.unit` is never read: it is a lazy
  relationship and would raise `DetachedInstanceError`, which is the rule
  `_account_tree_rows` documents. This works because every session factory
  sets `expire_on_commit=False`, which `_fetch_row` already relies on for
  `Priced.close`.
- **The last column stays last by construction.** Each row is a dict literal
  with `**_market_columns(row)` between `quantity` and the last column, and
  tabulate orders columns by key insertion.

### 6.2 `net-worth` (035, 036)

```
section, unit, quantity, **_market_columns(row), "at cost": row.balance.at_cost
```

- **The `tabulate` call gains `missingval="-"`.** It has none today. The
  existing `at cost` column never holds `None`, so it renders identically.
- **Three lines follow the table, on every ledger.** Unlike `balance`,
  there is no M > 0 condition: net worth always has a market figure to
  report, and the spec keeps its output shape independent of the data.
  - `\nNet worth (at cost): {report.at_cost.net_worth_at_cost:.2f}` is
    unchanged, including the blank line before it.
  - `Net worth (at market): {report.net_worth_at_market:.2f}` is added in 035.
  - `_estimates_line(report.estimates)` is added in 036.
- **The label is `Net worth (at market)`.** It pairs with the at-cost label,
  so `grep 'Net worth ('` finds both.

```
section               unit            quantity    price  price date      market value  status                at cost
--------------------  ------------  ----------  -------  ------------  --------------  ------------------  ---------
Own accounts          EUR              4796.00     -     -                    4796.00  -                     4796.00
Own accounts          IE00B4L5Y983       10.00   112.40  2026-10-09           1124.00  fresh                 1000.00
Own accounts          DE0005190003        3.00    80.50  2026-09-01            241.50  stale (2026-09-01)     225.00
Own accounts          XAU-G             100.00     -     -                    5500.00  no price (at cost)    5500.00
Receivables (People)  EUR                16.00     -     -                      16.00  -                       16.00

Net worth (at cost): 11537.00
Net worth (at market): 11677.50
2 of 3 holdings estimated (1 stale, 1 at cost)
```

(Rendered with the installed tabulate 0.9.0 from `Decimal` / `date` / `None`
values, not typed by hand.)

### 6.3 `balance` (038)

- **`No holdings` is checked first and is unchanged.** It gets neither new
  line.
- **Rows:** `unit`, `quantity`, `**_market_columns(row)`, `average cost`.
- **The `Total (base currency)` row** keeps today's condition: exactly one
  row, and it is `BASE_CURRENCY`. Its new keys are:
  - `price`: `None`;
  - `price date`: `None`;
  - `market value`: the quantity;
  - `status`: `None`;
  - `average cost`: `None`, as today.
- **Two lines follow the table, only when M > 0.** The callback computes
  `summary = summarise(rows)` first. Then, if `summary.holdings > 0`, it
  prints:
  - `\nMarket value: {at_market(rows):.2f}`;
  - `_estimates_line(summary)`.

  When M = 0 it prints neither. A euro-only account then differs from
  today's output only by the four columns. This is the user's decision,
  written into the re-frozen spec (§10.4).
- **The gate is `summary.holdings`, the same M the summary line reports.** It
  is not a separate test such as "any non-EUR row" or "no restatement row".
  Either of those would be a second definition of M, and both get
  zero-quantity rows wrong: a sold-out security is a non-EUR row, yet it is
  not a holding.
- **What the gate does at the edges:**
  - an account holding only a non-EUR currency has M = 1, and prints
    `1 of 1 holdings estimated (0 stale, 1 at cost)`;
  - an account whose only non-EUR row is sold out has M = 0, and prints
    neither line.
- **The total covers report rows only, never the restatement row.** The spec
  states this rule. With the gate, the two can no longer appear together:
  the restatement row needs the account's only row to be EUR, which means
  M = 0. The rule still holds by construction, because the CLI appends the
  restatement row to the table rows and never passes it to `at_market`.
- **The label is not `Total …`.**
  `test_balance_omits_total_row_for_multiple_units` asserts that `"Total"`
  does not appear anywhere in a multi-unit account's output, and the spec's
  list of constraining tests omits it (§10.1). `Market value:` also keeps
  "Total" meaning only the restatement row.
- **When the lines print, a blank line precedes them**, as in `net-worth`.

```
unit            quantity    price  price date      market value  status      average cost
------------  ----------  -------  ------------  --------------  --------  --------------
IE00B4L5Y983       10.00   112.40  2026-10-09           1124.00  fresh             100.00
DE0005190003        0.00     -     -                       0.00  -                   -
EUR               250.00     -     -                     250.00  -                   1.00

Market value: 1374.00
0 of 1 holdings estimated
```

A mixed account (M = 1, K = 0) prints both lines, above. A euro-only
account (M = 0) prints neither, below:

```
unit                     quantity  price    price date      market value  status      average cost
---------------------  ----------  -------  ------------  --------------  --------  --------------
EUR                         80.00  -        -                      80.00  -                   1.00
Total (base currency)       80.00  -        -                      80.00  -                   -
```

`test_balance_renders_none_average_cost_as_dash_without_breaking_other_rows`
still reads `1.00` and `-` as the last tokens of the `EUR` and `Total` rows.

### 6.4 The `floatfmt` / `missingval` trap

- **Numeric columns never hold a `str`.** `quantity`, `price`,
  `market value`, `average cost` and `at cost` hold only `Decimal` or `None`.
- **Text columns use `None` too.** `price date` (`date | None`) and `status`
  (`str | None`) do, so every `-` comes from one mechanism.
- **Checked against tabulate 0.9.0.**
  - `_type` classifies anything with `isoformat` as `str`, so a date column
    does not disturb its neighbours.
  - A `Decimal`/`None` price column keeps `.2f`.
  - An all-`None` column renders `-`.

### 6.5 The summary line (036)

- **Wording.** When K > 0 the line is
  `f"{K} of {M} holdings estimated ({S} stale, {C} at cost)"`. When K = 0 it
  is `f"0 of {M} holdings estimated"`.
- **When it prints differs by command, not by helper.**
  - `net-worth` prints it on every ledger, M = 0 included, as
    `0 of 0 holdings estimated`.
  - `balance` prints it only when M > 0 (§6.3), so from `balance` the K = 0
    form always has M ≥ 1.

  The condition lives in each callback, so `_estimates_line` does not need
  to know which command called it.
- **Fixed text.** There is no singular `holding`. The spec treats this line
  as grep vocabulary.
- **One helper.** `_estimates_line(summary: EstimateSummary) -> str` is
  shared by both commands.

### 6.6 The flag (037, 038)

```python
MAX_AGE_DAYS = click.option(
    "--max-age-days", type=click.IntRange(min=0), default=7, show_default=True,
    help="Days a close stays fresh; older closes are marked stale",
)
```

- **Defined once.** It is a module-level option beside `DECIMAL`. 037 applies
  it to `net_worth_cmd` and 038 to `balance_cmd`, so the two commands cannot
  drift.
- **Invalid values never reach a session.** Click rejects a negative or
  non-integer value with a usage error (exit 2) before the callback runs.
  That satisfies 037's "nothing is read".

---

## 7. Decimal handling and rounding (decision 7)

- **All arithmetic is `Decimal`, in the default context** (28 significant
  digits), like the fold and `_at_cost`.
  - `Fresh` / `Stale`: `quantity * close.price`. Both are `Numeric(20, 8)`
    read back as `Decimal`s quantised to 8 places (price-fetcher §6.2).
  - `NoClose`: `at_cost`. Average cost is already a 28-digit quotient.
  - Base currency: the quantity itself.
- **Nothing is quantised in the use case.** Rounding each row before summing
  would make the market total differ from the sum of the unrounded rows. It
  would also differ from how `_at_cost` is computed. Rounding happens only at
  display.
- **Display follows the existing split.**
  - Table cells go through tabulate's `floatfmt=".2f"`, which formats via
    `float`. That is today's behaviour for every numeric column.
  - Total lines use `Decimal`'s own `:.2f` (round-half-even under the default
    context), exactly as the at-cost line does.
  - The consequence already exists for the at-cost total: printed cells may
    not add up to the printed total by a cent. Totals are tested on
    `Decimal`s (§11).
- **The price column is shown to 2 places**, like average cost. A sub-cent
  close prints rounded. A per-column `floatfmt` was considered. Nothing asks
  for it, and it would make `balance`'s price and average-cost columns
  disagree in precision.
- **No local decimal context.** A product of two 8-place values exceeds 28
  significant digits only at magnitudes far beyond a personal ledger.

---

## 8. The decision categories

### State and data lifecycle

- **Reports write nothing.** No row, no `OperationGroup`, because groups are
  created lazily on the first write. Issue 039 pins this.
- **The unit of success is the whole report.** Either every row is valued or
  the command fails. There is no partial report: a missing row would break
  the spec's "the total always covers every holding".
- **Missing data is not failure.** `NoClose` is a value with a fallback. Only
  a database error fails a report.
- **Nothing to reverse.**
- **Replayable within a day, not across days.** The same ledger, the same
  `prices` table and the same `today` and N give the same output. That is
  why `today` is a parameter. Across days the output changes by design:
  closes age into `stale`, and `fetch-prices` appends new closes. That is
  exactly why fetching from a report was rejected (issue 039's rationale):
  the dependence on stored history is explicit and inspectable, and never on
  a source's answer at report time.
- **Not audited**, because nothing changes.
- **In memory:** `Price` objects inside `Fresh` / `Stale` outlive the session
  as detached, read-only values. Only their columns are read (§6.1).

### Error propagation

```
services        AccountError | JournalError (fold), PriceError (latest_price_service)
latest_close    Err(PriceError); a missing close is the value NoClose()
value_balances  Err(PriceError); the first failure ends the loop
use cases       Err(ValuationError) = BalanceError | PriceError
CLI             str(err) via ClickException, exit 1; flag errors exit 2 from click, before the callback
```

- **No new error class.** The feature has no new way to fail. An unknown
  account is the existing `AccountNotFoundError`.
- **`ValuationError` is a new alias.** It follows the
  `ListPriceTargetsError` precedent, which is the same union named for its
  use case. Reusing `ListPriceTargetsError` itself would name a report's
  error after the fetch path.
- **One representation change, in one place.** A `LatestClose` type becomes
  a status word only in `_market_columns`.
- **The reporting layer does not know why a close is missing.** The spec
  says that is `fetch-prices`' job.

### Concurrency and ownership

**Single-threaded, with no shared mutable state.**

- **One session per report command.** It is created by the CLI, owned by its
  `DbTransaction` and closed by it.
- **Immutable results.** `ValuedBalance`, `EstimateSummary` and
  `ValuedNetWorthReport` are frozen. Their lists are built once, by one
  function, and only read afterwards.
- **A concurrent `fetch-prices`** is serialised by SQLite on its own writes,
  and it can be seen mid-report (§5). That is harmless and not guarded.

### Reuse

Used rather than reimplemented:

- `account_balance`, `aggregate_by_unit`, `NetWorthReport` and `_at_cost`;
- `latest_close` and `LatestClose`, the spec's only price read;
- `BASE_CURRENCY`;
- `get_account_by_name_service`;
- `UnitOfWork._run` over a `ctx` function (the `WhoOwesWhat` shape);
- the `missingval` convention;
- `assert_never` matches (`_fetch_row`);
- the `date.today()` precedent of `fetch_prices_cmd`;
- in tests: monkeypatched module attributes and `_references` from
  `test_price_guards.py`.

Introduced here and worth reusing next:

- **`value_balances`**: any later report that values `UnitBalance`s, for
  example a positions view.
- **`ValuedBalance`**: unrealised gain is `market_value - balance.at_cost`
  per row.
- **`at_market` and `summarise`.**
- **`UnitBalance.unit_id` and `UnitBalance.at_cost`**: any presenter needing
  an id or the per-row cost figure.
- **`net_worth(ctx)`.**
- **`MAX_AGE_DAYS` and `_market_columns`.**

### Extension points

- **Unrealised gain** (a Non-Goal): `market_value - balance.at_cost` on a
  `ValuedBalance`. No field is added now.
- **Positions view:** `value_balances` over a cross-account fold of the
  `held_units` kind. `reporting.py` is its home.
- **Net worth over time** needs a "close on or before D" read, which does
  not exist (price-fetcher Non-Goal). `value_balances` is the one place that
  would switch reads. `today` already flows down, so it would become "as
  of". Nothing is parameterised now.
- **FX** (a Non-Goal): a non-EUR currency comes back `NoClose` and is valued
  at cost. A conversion would add a `LatestClose`-like outcome. Nothing is
  built.
- **TUI:** it would call `ValuedNetWorth` / `QueryValuedBalance`. The status
  words would then move from `_market_columns` into `reporting.py`, as one
  function moved, not rewritten.
- **The contract is `ValuedBalance`'s two fields and the `LatestClose`
  union.** A fourth `LatestClose` variant fails mypy at every `assert_never`
  (`market_value`, `_market_columns`). That is intended.
- **No plugin seam.** Reports never call plugins (039).

### Build vs. buy

- **Rendering:** tabulate, already a dependency, with `missingval`. Nothing
  new.
- **Flag validation:** `click.IntRange(min=0)`. It covers "non-negative
  integer" exactly. A custom `ParamType`, like `DECIMAL`, exists only because
  click has no decimal type.
- **Money arithmetic and formatting:** stdlib `Decimal`.
  - *`py-moneyed`* and *`babel`* bring currency objects and locale
    formatting.
  - Output is EUR-only `.2f` like every existing figure, and FX is a
    Non-Goal.
- **Valuation:** built.
  - It is three multiplications and a fallback over this ledger's own
    moving-average fold.
  - A portfolio library would bring its own position and cost model, which
    would disagree with `aggregate_by_unit` (cli-record-and-balances §6.4).
- **No cache.** That means no `functools.cache` and no shared lookup across
  sections. It is one indexed query per unit per section, inside one
  transaction.

### Abstractions introduced

| Abstraction | Forcing problem |
|---|---|
| `kohle/use_cases/reporting.py` | The guard keeps price reads out of `journal.py`. Issue 039 needs report code apart from `prices.py`'s writers (§2.1). |
| `ValuedBalance` | Each row needs its close for price, date and status. `UnitBalance` cannot hold a price type under the guard (§4.1). |
| `ValuedBalance.market_value` | The valuation rule shared by both reports and tested without a database (§4.1). |
| `value_balances` | The one place a close is read and the one place the lookup condition is written, shared by both reports (§4.3). |
| `at_market` | One definition of the market total, the mirror of `_at_cost`, for both reports (§4.4). |
| `EstimateSummary`, `summarise` | Four counts, one derived, shared by both reports. A bare tuple of three `int`s would let a transposition type-check (§4.4). |
| `ValuedNetWorthReport` | Two valued sections, plus the unchanged at-cost report the byte-identical line must come from (§4.5). |
| `ValuedNetWorth`, `QueryValuedBalance` | One transaction per report (spec), which only a `UnitOfWork` gives (§5). |
| `net_worth(ctx)` | `ValuedNetWorth` needs `NetWorth`'s partition inside its own transaction (§2.4). |
| `UnitBalance.unit_id` | `latest_close` keys by id. The fold has it and would otherwise discard it (§3). |
| `UnitBalance.at_cost` | The spec's "reuses exactly that per-row figure". The formula already had two copies (§4.2). |
| `ValuationError` | The use cases' `Err` type, named for them (Error propagation). |
| `MAX_AGE_DAYS` | One flag definition for two commands (§6.6). |
| `_market_columns`, `_estimates_line` | One rendering for two commands. Issue 038 forbids a second copy (§6.1, §6.5). |

Explicitly **not** introduced:

- **A status enum or a stored status string.** `LatestClose` already is the
  status. A string field would be matched by text.
- **A base-currency flag on the valuation** (§4.1).
- **A per-row error type.** A missing close is `NoClose`. A database failure
  fails the report.
- **A clock abstraction.** `today` is a parameter, and CLI tests patch the
  module attribute (§11).
- **A threshold setting, a config file, or a shared default constant** (§5).
- **A report wrapper around `balance`'s list** (§4.5).
- **A callable "close reader" seam for `value_balances`.** The rule is
  already pure in `market_value`. The lookup condition is tested against the
  in-memory `session` like every other `ctx` function.
- **`kind` or a `Unit` object on `UnitBalance`** (§3, §4.3).

### Alternatives rejected

| Rejected | Where | Short reason |
|---|---|---|
| Valuation in `journal.py` | §2.1 | the guard forbids it, directly and transitively |
| Valuation in `prices.py` | §2.1 | it holds the writers; 039's "names no writer" check would be unwritable |
| Composition in the CLI | §2.2 | two transactions; the CLI has no `ctx`; the rule would live in one frontend |
| Moving `QueryAccountBalance` / `NetWorth` into `reporting.py` | §2.3 | seven test files import them from `journal.py`; re-export fails the guard |
| `today` / `max_age_days` on `QueryAccountBalance` / `NetWorth` | §2.3 | they live in `journal.py`, and the tests call them without |
| Copying `NetWorth`'s partition into `ValuedNetWorth` | §2.4 | two definitions of net worth |
| Resolving the unit id via `get_unit_by_identifier_service` | §3 | a query per row and an impossible `UnitError`, to recover what the fold dropped |
| Carrying the `Unit` ORM object on `UnitBalance` | §3 | an ORM object in a value type that outlives the session; `kind` invites a distinction the spec forbids |
| Grouping the fold by `unit_id` | §3 | changes the fold's key under its pure tests, whose lines have no ids |
| `unit_id: int \| None` | §3 | weakens every real reader to satisfy transient test lines |
| A separate base-currency flag on the valuation | §4.1 | admits two invalid combinations instead of one |
| A third copy of `quantity * average_cost` in the `NoClose` arm | §4.2 | the spec says "reuses exactly"; mypy would demand an impossible `None` branch |
| Skipping lookups for non-security units | §4.3 | needs `kind` on `UnitBalance`; the spec does not tell them apart |
| Counting S and C from rendered status strings | §4.4 | couples the counts to wording |
| Recomputing the at-cost line from valued rows | §4.5 | byte-identity by re-derivation instead of by the same property |
| Status words in the use case | §6.1 | `_fetch_row` precedent: types cross the boundary, words are rendered |
| Average cost in the `price` column for `NoClose` | §6.1 | presents cost as a close |
| `Total (market value)` as `balance`'s label | §6.3 | `test_balance_omits_total_row_for_multiple_units` asserts `"Total"` is absent |
| Counting the `Total (base currency)` row in the market total | §6.3 | doubles a single-EUR account |
| Always printing `balance`'s two lines | §6.3, §10.4 | superseded by the user: noise on every euro-only account, such as `0 of 0 holdings estimated` under an expense category |
| Gating `balance`'s lines on "any non-EUR row" or "no restatement row" | §6.3 | a second definition of M that counts sold-out positions |
| Moving the M > 0 condition into `_estimates_line` | §6.5 | the helper would need to know which command called it; `net-worth` prints regardless |
| A `balance` at-cost total | spec | the spec rules it out; per-row cost is visible |
| `str` dashes in numeric columns | §6.4 | disables `floatfmt` for the whole column |
| Per-row quantisation to cents | §7 | totals would stop equalling the sum of rows, unlike `_at_cost` |
| Per-column `floatfmt` for the price | §7 | not asked for; price and average cost would disagree in precision |
| A shared `DEFAULT_MAX_AGE_DAYS` constant | §5 | reopens price-fetcher §8; saves one literal |
| Removing `latest_close`'s default | §5 | breaks `test_latest_close` |
| Caching closes across sections | §4.3 | the spec counts per section; one indexed query per row |
| A partial report on a failed read | Error propagation | a missing row breaks "the total covers every holding" |
| Fetching from a report | spec, 039 | the same ledger would report differently on different days |

---

## 9. Issue mapping (decision 6)

| Issue | Lands |
|---|---|
| 035 | `journal.py`: `UnitBalance.unit_id` (last field, from `line.unit_id`); `UnitBalance.at_cost`; `_at_cost` over it; `net_worth(ctx)` and `NetWorth` on it, with the docstring sentence updated. `domain_errors.py`: `ValuationError`. `reporting.py`: `ValuedBalance`, `value_balances`, `at_market`, `ValuedNetWorthReport` with `net_worth_at_market`, `ValuedNetWorth`. `cli.py`: `_market_columns`; `_net_worth_rows` over `ValuedBalance` with `at cost` from `at_cost`; `net_worth_cmd` on `ValuedNetWorth(...).execute(date.today(), 7)`; `missingval="-"`; the `Net worth (at market)` line; the `NetWorth` import is dropped from `cli.py`. README "Net worth": the new example and the at-cost-only paragraph rewritten. Tests (§11). |
| 036 | `reporting.py`: `EstimateSummary`, `summarise`, `ValuedNetWorthReport.estimates`. `cli.py`: `_estimates_line`, printed after the market line in `net_worth_cmd`. The README example gains the line and a sentence on what it counts. Tests on the mixed ledger with K, S, C and M asserted, plus the K = 0 form. |
| 037 | `cli.py`: the `MAX_AGE_DAYS` option, applied to `net_worth_cmd`, whose value replaces 035's literal `7`. README documents the flag. Tests: the boundary pair at 7 and at a non-default N; `-1` and `x` exit 2 with nothing read. |
| 038 | `reporting.py`: `QueryValuedBalance`. `cli.py`: `balance_cmd` on it with `MAX_AGE_DAYS`, `_market_columns`, the extended `Total (base currency)` row, and, only when `summarise(rows).holdings > 0`, the `Market value:` line followed by `_estimates_line(summary)`; the `QueryAccountBalance` import is dropped from `cli.py`. README "Reading the ledger": "There is no market valuation yet …" replaced, with an example of a mixed account and a sentence saying a euro-only account shows the columns only. Tests (§11): a euro-only account prints neither line; a mixed account prints both. |
| 039 | `tests/test_price_guards.py`: the read-only behaviour test, and the exact-identifier check over both callbacks and over `kohle/use_cases/reporting.py` (§10.6, now in the issue). |

**Order: 035 → {036, 037} → 038 → 039.**

- 036 and 037 are independent of each other.
- 038 needs both: 036 for the summary and its `holdings` gate, and 037 for
  the flag.
- 039 declares 035 and 038, and lands last (§10.6).

**What 036 and 038 add is fully specified above**, so the implementer has no
further decisions to make:

- 036 adds the counts on the use-case side (§4.4), one property (§4.5), and
  one CLI helper and one line (§6.5).
- 038 adds one use case (§4.5) and the `balance` rendering (§6.3),
  including the M > 0 gate. Every helper it uses already exists by then.

**Scaffolding forced by the issue boundaries.** These are the only two
cases:

1. **035 passes the literal `7`** from `net_worth_cmd`, because 035 requires
   the threshold "passed as a parameter" and the flag arrives in 037. 037
   replaces the literal with the option's value. Below the CLI, nothing
   changes between the two slices.
2. **`MAX_AGE_DAYS` has one user from 037 until 038.** It is defined
   module-level in 037 so that 038 only applies it.
039 adds no scaffolding. It now declares 038 and lands last, so its
`balance` half exercises the valuing path from the start.

`UnitBalance.unit_id` is used only by net worth until 038. That is not
scaffolding, because it is permanent.

---

## 10. What the spec and the issues got wrong, or left open

Recorded because the design settles them or deviates, and a later reader
needs to know that was deliberate.

1. **An unlisted test constrained `balance`'s market line.** *Adopted: the
   spec and issue 038 now say so.* The first spec's "Existing tests that
   constrain layout" omitted `test_balance_omits_total_row_for_multiple_units`.
   That test asserts `"Total" not in result.output` for a two-unit account,
   so the label cannot contain `Total`. The design uses `Market value: X`
   (§6.3).
2. **The `missingval` convention existed only in `balance`.** *Adopted: the
   spec now says `net-worth` gains it.* `net_worth_cmd` passes no
   `missingval` today, so `None` would render blank. 035 adds
   `missingval="-"` there (§6.2).
3. **"The `balance` market total equals the sum of its rows' market values"
   was ambiguous.** *Adopted: the spec and issue 038 now exclude the
   restatement row.* That row has a market value, the quantity, as the spec
   requires, so summing the printed table would double a single-EUR account.
   The design sums report rows only (§6.3).
4. **Every base-currency-only `balance` would have printed two more lines.**
   *Resolved by the user: the spec was revised and re-frozen.* Under the
   first spec, `balance Groceries` would have ended with
   `Market value: 80.00` and `0 of 0 holdings estimated`, beneath a
   `Total (base currency)` row that already says 80.00.
   - **The user's decision:** `balance` prints both lines only when M > 0.
     When M = 0 it prints neither, so a euro-only account differs from today
     only by the new columns.
   - **`net-worth` is unchanged:** it always prints both, including
     `0 of M holdings estimated`.
   - **The spec's "the output shape does not depend on the data" now applies
     to `net-worth` only.**

   The rendering is in §6.3, and the tests are in §11.
5. **035's README criterion quoted a phrase from the wrong section.**
   *Adopted: issue 035 was edited to match.* "no market valuation yet" is in
   "Reading the ledger", which describes `balance`, and `balance` is not
   valued until 038.
   - **035 rewrites the net-worth section's own at-cost-only paragraph**
     ("Every figure is reported at recorded cost … deferred
     `portfolio-and-profit-reporting` work").
   - **038 replaces the balance sentence**, as its own criterion says.
6. **Issue 039.** *Adopted: issue 039 was edited to match.*
   - **It now declares "Depends on: 035, 038" and lands last.** Its
     `balance` half means something only after 038.
   - **Its exact-identifier check now covers `kohle/use_cases/reporting.py`
     as well as the two callbacks.** `inspect.getsource` of a callback sees
     neither the CLI helpers nor the use case, and the use case is where a
     writer would realistically be added. The check is on identifiers, not
     modules, because `reporting.py` legitimately imports `latest_close`,
     `Fresh`, `Stale`, `NoClose` and `LatestClose` from
     `kohle.use_cases.prices`. None of those is in the forbidden set
     `{load_price_plugins, PriceFetcherPlugin, call_price_plugins,
     AppendPrices, add_price_service}`.
7. **037's CLI boundary pair needs a pinned `today`.** *Adopted: issue 037
   was edited to match.* The CLI reads `date.today()`, so the CLI test pins
   it by monkeypatching `kohle.app.cli.cli.date` with a `date` subclass
   whose `today()` is fixed. That is the same module-attribute seam the
   price CLI tests use for `load_price_plugins`, with no clock abstraction.
   The exact 7/8-day pair is also pinned at the use-case level with an
   explicit `today`.
8. **"People-subtree rows are base currency" is an assumption, not a rule
   the code enforces.** The design applies the per-row rule to receivables
   with no section special case. A non-EUR currency owed by a person comes
   back `NoClose`, and is valued at cost, which is today's figure. A security
   owed by a person would be valued at its close. Both follow from the spec's
   per-row rule.
9. **`QueryAccountBalance` and `NetWorth` lose their only production
   caller** (§2.3). This is forced by the tests that pin them, and recorded
   so it is not read as an oversight.
10. **Expense-splitting §9.4 says net worth "swaps `average_cost` for the
    latest `Price`".** The spec puts market value *alongside* cost instead,
    and the design follows the spec. §9.4's actual seam, "per row, quantity
    × per-unit value", is what `market_value` is.
11. **"The net-worth market total equals the sum of the market values of all
    rows" holds exactly on `Decimal`s.** *Adopted: the spec now has a
    Rounding bullet.* On the printed 2-place cells it can differ by a cent,
    as the at-cost total already can. The equality is tested at the use-case
    level, or at the CLI with fixtures that are exact to 2 places (§7, §11).

**Post-landing:** `AGENTS.md`'s Context already says prices are "read only
by reporting", which becomes literally true. No edit is required.

---

## 11. Testing notes

This extends the existing layers: pure functions with no fixture, use cases
against `session`, the CLI through `CliRunner` with `session_factory`, and
guards. Closes are seeded with `session.add(Price(...))`, as
`test_latest_close` does. Reports read no bindings, so no binding is needed.

**Pure, no database:**

- `ValuedBalance.market_value`:
  - `Fresh` and `Stale` give quantity × close;
  - `NoClose` gives `balance.at_cost`, i.e. quantity × average cost;
  - `None` on an EUR row gives the quantity;
  - `None` on a zero-quantity row gives 0;
  - a negative quantity × close is negative.
- `UnitBalance.at_cost`: a nonzero row, and a `None` average cost giving 0.
- `at_market`: a mixed list, and an empty list giving `Decimal(0)`.
- `summarise`:
  - on a mixed list (EUR, fresh, stale, no close, a zero row), with K, M, S
    and C asserted;
  - an empty list gives all zeros;
  - an EUR-only list gives M = 0, which is `balance`'s "print neither line"
    case.

**Use case (`session`, pinned `TODAY`):**

- `value_balances`:
  - an EUR row and a zero-quantity security row get `close is None`, even
    when the zero row's unit has a stored close (this pins "no close is
    looked up");
  - an unbound security and a commodity come back `NoClose`;
  - row order is preserved.
- Boundary, at the use-case level:
  - with N = 7, a close dated `TODAY - 7` is `Fresh` and `TODAY - 8` is
    `Stale`;
  - with N = 3, `TODAY - 3` is `Fresh` and `TODAY - 4` is `Stale`.
- `ValuedNetWorth` on one mixed ledger:
  - EUR cash, a fresh security, a stale security, a never-fetched security
    and a sold-out position, plus an EUR receivable;
  - the security held in two depots gives one row whose market value is the
    summed quantity × close;
  - `at_cost`'s three properties equal `NetWorth(session).execute()` on the
    same ledger;
  - `net_worth_at_market` equals the sum of `market_value` over both
    sections;
  - `estimates` (036) gives K, M, S and C.
- `QueryValuedBalance` (038): the same rule on a subtree; an unknown account
  is `Err(AccountNotFoundError)`.

**CLI:**

- **`net-worth`:**
  - the header tokens are exactly `section unit quantity price price date
    market value status at cost`;
  - each data row's last token is its formatted at-cost value;
  - `Net worth (at cost): X` matches verbatim;
  - `Net worth (at market): Y` and the summary line are present **on every
    ledger**, asserted on two:
    - on a euro-only ledger (M = 0), the last two lines are
      `Net worth (at market): X` and `0 of 0 holdings estimated`;
    - on a mixed ledger, the summary carries K, M, S and C.
  - Status cells contain spaces, so assert them by substring within a row,
    not by token position.
- **`balance`:**
  - the header order;
  - the `Total (base currency)` row shows `-` in price, price date, status
    and average cost, and the quantity in market value;
  - **a euro-only account (M = 0) prints neither line.** The output
    contains neither `Market value` nor `holdings estimated`, and its last
    line is the table's last row, so it differs from today only by the four
    columns;
  - **a mixed account prints both.** Take EUR plus a security with nonzero
    quantity. `Market value: X` and the summary line are the last two lines,
    and X is the sum of the unit rows only;
  - a mixed account with K = 0 prints `0 of M holdings estimated`, with
    M ≥ 1;
  - an account whose only non-EUR row is a sold-out position (M = 0) prints
    neither line, which pins the gate to M rather than to "any non-EUR row";
  - `No holdings` output is unchanged.
- **`--max-age-days`:**
  - `-1` and `x` exit 2, with `obj=` a factory that fails the test if
    called (the `forbidden_session_local` pattern);
  - the boundary pair through the monkeypatched `kohle.app.cli.cli.date`
    (§10.7);
  - a mid-range check seeded relative to the real `date.today()` uses ages
    well away from N, so a midnight rollover cannot flip it.
- **Existing tests stay unchanged**, and the dash test,
  `test_balance_omits_total_row_for_multiple_units`, the net-worth CLI test
  and `test_no_price_plugins_means_no_output_change` are the regression net.
  The last of these passes because both of its runs read the same empty
  `prices` table, and reports load no plugin.

**Guards (039), in `tests/test_price_guards.py`:**

- **Behaviour.** Use a ledger with a fresh, a stale and a never-fetched
  security. Count the `prices`, `operations` and `operation_groups` rows,
  run `balance` and `net-worth` through `CliRunner`, and assert all three
  counts are unchanged.
- **Static.** Run `_references` over `inspect.getsource` of
  `balance_cmd.callback` and `net_worth_cmd.callback`, and over
  `kohle/use_cases/reporting.py`. Assert that none references
  `load_price_plugins`, `PriceFetcherPlugin`, `call_price_plugins`,
  `AppendPrices` or `add_price_service`. This reuses the existing
  exact-identifier walk.
