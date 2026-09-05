# Design: CLI record and balances

Spec: `dev/specs/cli-record-and-balances.md` (frozen)
Issues: `dev/issues/001`–`008`

Layering per `AGENTS.md` stays `app -> use_cases -> services ->
infrastructure/domain`. Only services touch a `Session`.

---

## 1. Summary of the shape

| File | Change |
|---|---|
| `kohle/app/cli/cli.py` | add `record`, `record-split`, `balance`, `list-operations`; rewrite `list-accounts` as a tree |
| `kohle/use_cases/journal.py` | add `LineInput`, `CrossUnitLine`, `UnitBalance`, `post_entry`, `RecordSimpleEntry`, `RecordSplitEntry`, `QueryAccountBalance` |
| `kohle/services/account_services.py` | add `descendant_account_ids_service` (recursive CTE) |
| `kohle/services/journal_services.py` | widen `account_lines_service` to take an id collection; map the journal-line unique constraint |
| `kohle/domain/domain_errors.py` | add `BaseCurrencyAsCrossUnit`, `DuplicateLineInEntry`, and two union aliases |
| `kohle/services/operation_services.py` | add an `ORDER BY` |

No new modules, no schema change, no migration.

`use_cases/journal.py` grows to roughly 400 lines. It is not split into a
`reporting.py`: `QueryJournalByPeriod` — the existing read-side use case —
already lives there, so a new module would scatter reads across two files and
create exactly the parallel structure that should be avoided. If
`portfolio-and-profit-reporting.md` later lands FIFO lots, that is the point
to split, and it should take `QueryJournalByPeriod` with it.

---

## 2. `record` — which side carries the non-base unit

This is the spec's first Open Question and the substantive decision.

### 2.1 Chosen: side-prefixed unit flags, with no unprefixed form

```
kohle-cli record ENTRY_DATE DESCRIPTION QUANTITY --from CREDIT_ACCOUNT --to DEBIT_ACCOUNT
                 [--from-unit UNIT --from-price PRICE]
                 [--to-unit   UNIT --to-price   PRICE]
```

There is no bare `--unit` / `--price`. The four flags above are the only way
to name a non-base unit.

Base-currency entry (issue 001) — no unit flags at all:

```
kohle-cli record 2026-03-01 "Withdraw cash" 200 --from Checking --to Unallocated
```

Purchase (issue 004) — the unit arrives on the debit side:

```
kohle-cli record 2026-03-06 "Buy ETF" 10 --from Checking --to Broker \
                 --to-unit IE00B4L5Y983 --to-price 100
```
→ debit `Broker` 10 × IE00B4L5Y983 @ 100; credit `Checking` 1000 × EUR @ 1.

Sale — the unit leaves on the credit side:

```
kohle-cli record 2026-04-20 "Sell ETF" 10 --from Broker --to Checking \
                 --from-unit IE00B4L5Y983 --from-price 110
```
→ credit `Broker` 10 × IE00B4L5Y983 @ 110; debit `Checking` 1100 × EUR @ 1.

**One rule governs all three:** QUANTITY is denominated in the unit named on
the side it was named on; the opposite side is the same *value* in base
currency, quantity `QUANTITY × PRICE` at price 1. The base-currency case is
that rule with the unit defaulting to EUR on both sides and the price to 1,
where `QUANTITY × 1 = QUANTITY` makes the two sides coincide.

### 2.2 Why this shape, judged on mistakability

The failure the spec names is that a sale mis-entered as a purchase produces
no error — it balances by value, both accounts are leaves, `validate_lines`
passes, and the wrong entry is committed. So the flag shape has to be judged
on how easy it is to *write* the wrong thing, not on how it reads once
correct.

**There is no default direction, because there is no unprefixed flag to
default.** Every alternative below has a form where the direction is implied
by something the user can omit or forget. In this design, naming a non-base
unit without naming its side is not expressible — the side is part of the
flag name, and the flag name is the only channel. A command line that omits
the direction does not silently pick one; it does not parse.

**The direction lives in one place, not two.** The natural way a user
produces a sale is to recall the purchase from shell history and swap the two
account names. Under this design, swapping `--from Checking --to Broker` and
leaving `--to-unit IE00B4L5Y983` yields a command line that literally reads
"Checking receives 10 IE00B4L5Y983" — the mistake is visible in the text.
Under any design where the side is a separate flag, the swap leaves that flag
stale and the text still reads plausibly.

**The two directions cost the same.** `--from-unit`/`--from-price` and
`--to-unit`/`--to-price` are the same shape and the same amount of typing.
Neither is what you get by leaving something out. That is the spec's
"equally reachable" constraint satisfied by symmetry of the surface rather
than by a documented convention.

Cost, stated plainly: four flags in `--help` instead of two, and a reader has
to notice `--to-unit` and `--to-price` are a pair. That is accepted.

### 2.3 Alternatives rejected

**Hardcode "`--to` always carries the non-base unit."** Rejected by the spec
itself; recorded here because it is the shape that a naive reading of the
spec's own ETF example suggests, and it will be re-proposed. It expresses a
purchase and cannot express a sale, and a user who writes the sale anyway
(`--from Broker --to Checking --unit X --price 110`) gets a committed entry
saying Checking holds 10 units of X. Silent, and exactly the corruption the
spec's Goals call out.

**A separate `--unit-side from|to` flag alongside a bare `--unit`/`--price`.**
Rejected. The direction is then stated twice — once by `--from`/`--to`, once
by `--unit-side` — with nothing enforcing agreement. The history-edit path
above breaks it: swap the accounts, forget the side flag, get a silently
inverted entry. It also needs a default, and whichever default is chosen
re-creates the hardcoded case for anyone who omits the flag.

**A `--unit-account ACCOUNT` flag naming the account rather than the side.**
Rejected. It looks like it converts a silent error into a hard one — name an
account not in the entry and it fails — but in the actual failure mode the
user names one of the two accounts that *are* in the entry, just the wrong
one. It catches typos and catches nothing else, at the cost of writing an
account name twice.

**Infer the direction from `AccountType`.** Rejected, and it does not work at
all: the ETF purchase moves value between `Checking` (asset) and `Broker`
(asset). Types are equal on both sides in every securities transaction, and
in the cash-envelope scenario every account in play is an asset too. Even
where types did differ, the rule would be an invisible inference the user
could not audit from the command line.

**Separate `buy` / `sell` commands.** Rejected, though it is the option that
reads best and will be raised again. Three reasons. First, it fails the spec
as written — the constraint is that both directions are reachable *through
`record`*; adding sibling verbs and leaving `record` base-currency-only does
not satisfy it. Second, it does not actually remove the problem, it relocates
it: inside `buy`, `--to` implicitly carries the unit, and inside `sell`,
`--from` does, so the same hardcoded-side convention is back, now differing
between two commands that sit next to each other in shell history. Third, it
doubles the command surface to carry one bit.

**Give both sides full line syntax.** Rejected: that is `record-split`, which
this slice already builds. The whole point of `record` is to derive the
second line.

### 2.4 Known gap this shape creates

A same-unit transfer of a *non-base* unit — moving 10 shares from `Broker A`
to `Broker B` — is not expressible in `record`, because the spec fixes the
derivation as "the other side is derived in base currency". Any non-base
`--from-unit`/`--to-unit` therefore always produces a base-currency
counter-side. Such a transfer goes to `record-split`, where both lines are
written in full. Flagged rather than worked around: the spec fixed that
derivation, and inventing a third mode ("both sides same unit") would put a
second rule into the shorthand, which is what makes shorthands mistakable.

---

## 3. `--price` with a base-currency unit (Open Question 2)

**Rejected, and rejected in the use case rather than in the CLI.**

Under the chosen flag shape the question sharpens. `--to-unit EUR
--to-price 1.1` is not a user idly passing a redundant flag; it is a user who
typed a side prefix — a prefix that exists only for the cross-unit case — and
then named the base currency. That is a mistaken belief about what they are
recording, not noise.

The two ways of not rejecting are both worse:

- *Honour the price.* It balances (`Q × 1.1` on both sides), `validate_lines`
  accepts it, and it commits a line asserting that the account holds Q euros
  that cost 1.1 each. The base currency's price is 1 by definition; anything
  else corrupts the average cost `balance` computes for EUR, silently and
  permanently, since the ledger is append-only.
- *Ignore the price.* The correct entry posts and the user is never told that
  part of their command was discarded.

The rule is generalised one step further than the spec's: **`--from-unit` /
`--to-unit` are for non-base units only.** Naming `EUR` there is rejected
whether or not a price accompanies it, with one message ("the base currency
is the default; omit the unit flags"). One rule instead of two, and it keeps
`CrossUnitLine` a type that genuinely never holds the base currency.

Placement: this check is a *use-case* rule with a domain error
(`BaseCurrencyAsCrossUnit`), not a CLI check. It compares against
`BASE_CURRENCY`, which is a ledger constant, and a second frontend needs the
same rule. The CLI keeps only the two pure shape checks in §5.1.

---

## 4. `balance` — no `--own` flag (Open Question 3)

**Not added.** The reasoning is worth recording because the flag looks
obviously useful and is not.

For a leaf account, `--own` and the default produce identical output. For a
parent account, `--own` is empty by construction, because leaf-only posting
means a parent cannot have lines. So across the ledger's valid states the
flag has no case where its output is not predictable in advance.

It has exactly one informative case: an account that had lines posted to it
and *then* gained a child, so its own postings are stranded and the rollup
double-reports nothing but the account is no longer postable. The spec names
this state in its Non-Goals as a real, unaddressed gap. `--own` would detect
it — but only if the user thinks to run it, which is precisely what someone
unaware of the problem will not do. A diagnostic that requires suspecting the
bug is not a detector.

The right answer to that condition, when it becomes worth solving, is for
`balance` to *report* it — warn when any non-leaf account inside the walked
subtree has lines of its own. That is one extra predicate over data the
rollup already loads. It is left out here because the spec puts stranded
postings in Non-Goals, and recorded as the thing that would justify the work.

---

## 5. `record` and `record-split` — where each piece lives

### 5.1 CLI (`kohle/app/cli/cli.py`)

The CLI does exactly three things: convert argument text to typed values,
reject flag combinations it cannot turn into a use-case call at all, and
print a `Result`.

The line between "CLI parsing" and "validation the CLI must not do":

> The CLI may reject input it cannot construct a use-case call from. It may
> not reject a use-case call it managed to construct.

Everything below the line is a ledger rule and belongs to `validate_lines` or
a use case. The CLI's rejections are therefore:

1. Both `--from-unit` and `--to-unit` given.
2. `--from-price` without `--from-unit`, or `--to-price` without `--to-unit`
   (and the reverse).
3. `--line` not splitting into exactly five colon-separated fields, or a
   field that is not a `Decimal` / not `debit`|`credit`.

All three are statements about the *shape* of the invocation. None consults
the database and none knows a ledger rule. Balance-by-value and leaf-only
posting stay solely in `validate_lines`, untouched.

`click.BadParameter` is raised for these. This is a deliberate, narrow
exception to the project's "return `Result`, do not raise" rule: Click
catches it inside its own parameter-processing loop and renders the standard
`Error: Invalid value for '--line': ...` with exit code 2. It never crosses a
layer boundary — it is raised and caught entirely inside Click. Reimplementing
this as `Result`-returning parsers would duplicate Click's machinery and
produce worse messages.

Typed conversion happens here, not in the use case:

- `ENTRY_DATE` via `click.DateTime(formats=["%Y-%m-%d"])`, then `.date()`.
- `QUANTITY`, `--*-price`, and the `--line` numeric fields via a small
  `DecimalParamType(click.ParamType)`. Click 8.3 has no `Decimal` type
  (verified) and `type=float` must not be used — `Decimal(0.07)` is not
  `Decimal("0.07")`, and this is a money ledger.

This is a deliberate divergence from `QueryJournalByPeriod`, which takes date
*strings* and parses them internally with `parse_date`. That signature is a
wart, not a pattern: it forces any frontend holding a real `date` to
stringify it just to have a parser re-parse it, and a Textual date widget
holds a real `date`. `QueryJournalByPeriod` is not changed — out of scope —
but the new use cases take typed values, and `parse_date` is left where it
is.

Command names follow the existing derivation (Click 8.2+ strips a trailing
`_cmd`, verified): `record_cmd` → `record`, `record_split_cmd` →
`record-split`, `balance_cmd` → `balance`, `list_operations_cmd` →
`list-operations`.

### 5.2 Use cases (`kohle/use_cases/journal.py`)

Three small types, each with a forcing problem:

```
LineInput      account_name, quantity, unit_identifier, unit_price, is_debit
CrossUnitLine  identifier, price, is_debit
UnitBalance    unit_identifier, quantity, average_cost
```

- **`LineInput`** — the name-shaped twin of `LineSpec`. Forced: the CLI has
  account and unit *names* and cannot resolve them to ids (no `Session`), and
  `LineSpec` requires ids. Something must carry a line across that boundary.
  A frozen dataclass mirroring `LineSpec` field-for-field is the minimum
  form; the alternative is parallel lists or bare tuples.
- **`CrossUnitLine`** — carries the unit, its price, and which side holds it.
  Forced: those three values are mutually dependent — a price without a unit
  is meaningless, a side without a unit is meaningless — and passing them as
  three independent `| None` parameters makes the invalid combinations
  representable at the use-case boundary, so the use case would have to
  re-reject what the CLI already rejected. As one optional value, "price
  without unit" cannot be constructed.
- **`UnitBalance`** — a detached value type so `balance`'s result survives
  the session closing. See §6.3.

Two new use cases, both `UnitOfWork` subclasses and both siblings of
`RecordJournalEntry`, not wrappers around it:

```
RecordSimpleEntry.execute(entry_date, description, quantity,
                          from_account, to_account, cross: CrossUnitLine | None)
RecordSplitEntry.execute(entry_date, description, lines: list[LineInput])
```

They cannot delegate to `RecordJournalEntry`, and the reason is structural
rather than stylistic: `UnitOfWork.__init__` takes a `Session`, and
`DbTransaction.execute` closes it in a `finally`. Calling one use case from
another would mean two sessions and two transactions — the account and unit
lookups committing separately from the posting. Each new use case therefore
runs its own `use_case(ctx)` closure, resolving names and posting inside one
`DbTransactionContext`.

Shared tail, factored out and used by `RecordJournalEntry`,
`RecordSimpleEntry` and `RecordSplitEntry`:

```python
def post_entry(ctx, entry_date, reference, description, lines: list[LineSpec])
    -> Result[JournalEntry, JournalError]
```

— the existing `validate_lines` call followed by `add_journal_entry_service`.
This makes "enforced exactly once in `validate_lines`" structural rather than
conventional: there is one call site.

`ImportStatement` is deliberately **not** folded into `post_entry`, even
though it inlines the same two calls. Its loop accumulates a counter and
short-circuits per row; converting it is a behaviour-neutral refactor of
working, tested code, and does not belong inside a feature slice.

`RecordSimpleEntry` body, in full:

```
resolve from_account, to_account          -> get_account_by_name_service
base_unit = get_or_create_unit(ctx, BASE_CURRENCY, "Euro", UnitKind.currency)

if cross is None:
    lines = [ LineSpec(to.id,   base_unit.id, quantity, 1, is_debit=True),
              LineSpec(from.id, base_unit.id, quantity, 1, is_debit=False) ]
else:
    if cross.identifier == BASE_CURRENCY: return Err(BaseCurrencyAsCrossUnit(...))
    cross_unit    = get_unit_by_identifier_service(ctx, cross.identifier)
    cross_account = to if cross.is_debit else from
    base_account  = from if cross.is_debit else to
    lines = [ LineSpec(cross_account.id, cross_unit.id, quantity,             cross.price, cross.is_debit),
              LineSpec(base_account.id,  base_unit.id,  quantity*cross.price, Decimal(1),  not cross.is_debit) ]

post_entry(ctx, entry_date, uuid4().hex, description, lines)
```

Note `get_or_create_unit` for the **base currency only**, matching
`ImportStatement`. The spec's no-auto-vivification rule targets what the user
types — `--from`, `--to`, `--from-unit`, `--to-unit` all use the strict
`get_*_service` lookups, so a typo is an error and never silently creates an
account or unit. `BASE_CURRENCY` is a module constant the user never types;
auto-creating it cannot mask a typo, and the alternative is that a fresh
install's first `record` fails with "Unit EUR not found" for a unit the user
did not mention. *Flagged for review: this is a reading of the spec's rule as
scoped to user-supplied names, not an exception to it, but the spec's
sentence says "`--unit` must already exist" and under this flag design there
is no `--unit`.*

Reference is `uuid4().hex`, generated in the use case rather than the CLI —
`RecordJournalEntry` takes `reference` as a parameter because
`ImportStatement` supplies a content hash for idempotency, so "hand-entered
entries get a uuid" is a decision belonging to the hand-entry use cases. A
second frontend gets it without reimplementing.

Consequence, deliberate: two identical `record` invocations post two entries.
That is correct for hand entry — you can buy the same coffee twice — and is
the intended asymmetry with `ImportStatement`, whose hash exists so re-importing
a statement is a no-op.

Also deliberate, no check added: `record 100 --from Cash --to Cash` posts a
self-cancelling two-line entry. It balances, both lines are on a leaf, and the
unique constraint does not fire because the sides differ. It is a valid if
pointless entry, and reversing entries legitimately touch one account twice,
so there is no rule to enforce here.

### 5.3 `record-split`

```
kohle-cli record-split ENTRY_DATE DESCRIPTION --line ACCOUNT:QUANTITY:UNIT:PRICE:SIDE [--line ...]
```

`--line` is `multiple=True` with a `callback=` that splits on `:` into
exactly five fields, converts, and maps `debit`/`credit` to `is_debit`.
Colons are safe as the separator: account names carry spaces (`Eating out`)
but not colons, and ISINs and currency codes contain none. Malformed values
raise `click.BadParameter` naming the offending string, per issue 006.

`SIDE` accepts only `debit` and `credit`, as the issue fixes. `dr`/`cr` — the
abbreviations `entries-in-period` prints — are a trivial later alias and are
not added, because the spec fixed the vocabulary.

`RecordSplitEntry` resolves each `LineInput`'s account name and unit
identifier strictly, builds `LineSpec`s, and calls `post_entry`. Fewer than
two lines is caught by the existing `EmptyEntry` check inside `validate_lines`
— not by the CLI.

**One check that does not exist and is not being added to `validate_lines`.**
`JournalLine` carries `UniqueConstraint(entry_id, account_id, unit_id,
is_debit)`. A user writing `--line Groceries:10:EUR:1:debit --line
Groceries:20:EUR:1:debit` instead of combining them violates it, and today
`add_journal_entry_service` only maps the `journal_entries.reference`
constraint, so the failure surfaces as `JournalError(str(err))` — a raw
SQLAlchemy message. The fix chosen is to **map** the constraint in
`add_journal_entry_service` to a new `DuplicateLineInEntry` error whose
message is actionable ("two lines on the same account, unit and side; combine
them"), *not* to add a pre-check in `validate_lines`. Rationale: the database
already enforces the rule, a duplicated pre-check is the defensive code the
global rules forbid, and the constraint does not report which line collided
so a pre-check's only advantage would be naming it. Stated here explicitly
because it is a check that does not currently exist anywhere readable — if
naming the offending line turns out to matter, `validate_lines` is where it
goes, and it does not go in the CLI.

---

## 6. `balance` — the recursive-descendant query

### 6.1 Recursive CTE, not an application-side walk

`descendant_account_ids_service(ctx, account_id) -> Result[list[int], AccountError]`
in `kohle/services/account_services.py`, a SQLAlchemy `cte(recursive=True)`
over `Account.parent_id`, seeded with the account itself.

Chosen over the alternatives:

- **Application-side tree walk** (repeated `list_child_accounts_service`).
  Rejected: O(depth) round trips at best, O(nodes) if written per-node, and
  it round-trips ids out to Python and back into SQL for the lines query. A
  *recursive function* walk additionally hits Python's ~1000-frame recursion
  limit and, on a cyclic tree, blows the stack rather than terminating. The
  only thing it buys is avoiding a CTE, and SQLite 3.45 (verified in this
  venv) and SQLAlchemy 2.0.46 both support them directly.
- **Closure table / materialized path / nested sets.** Rejected as grossly
  disproportionate: an Alembic migration plus write-path maintenance on every
  account creation and every future reparent, to speed up a tree that is a
  handful of nodes deep in a single-user ledger.

The seed includes the account itself, so `balance Groceries` on a leaf
returns that leaf's lines and `balance Cash` includes any lines stranded
directly on `Cash`. Including the root is the conservative choice: stranded
postings are surfaced in the rollup rather than silently dropped.

### 6.2 Depth and cycles

**Depth.** SQLite evaluates a recursive CTE iteratively against a work queue,
not via a call stack — there is no recursion-depth limit to hit, and each
extra level costs one more iteration. A personal account tree is under ten
levels deep. No depth cap is imposed, because imposing one would mean
choosing an arbitrary number and failing on trees that are merely unusual.

**Cycles.** `parent_id` is written only by `add_account_service` at creation
time, with an already-existing parent, so a new account cannot be its own
ancestor. There is no reparenting command. A cycle therefore requires direct
database editing or a future "move account" feature. The design nonetheless
terminates on one, and the mechanism is specific and easy to break:

> Use `UNION`, not `UNION ALL`, and project **only `Account.id`** in the
> recursive term.

`UNION` deduplicates each new row against the accumulated result, so a cycle
stops producing new rows and the query terminates with the reachable set.
This was verified against SQLite 3.45 with cyclic parentage `1→3→2→1`:

| recursive term | result |
|---|---|
| `UNION`, projects `id` only | terminates, returns `{1,2,3,4}` |
| `UNION`, projects `(id, depth)` | does not terminate |
| `UNION ALL`, projects `id` | does not terminate |

The `(id, depth)` row is the trap: a monotonically increasing column makes
every row distinct, so `UNION`'s deduplication never fires. Anyone later
adding a depth or path column "for display" silently converts `balance` on a
corrupt tree from a wrong answer into a hang. That is a non-obvious WHY and
belongs as a comment on the CTE.

No cycle-detection error is added. Detecting and reporting a state the write
path cannot produce is defensive code for an impossible case, which the
global rules exclude. The `UNION` choice already guarantees termination,
which is the property that actually matters.

### 6.3 Fetching and aggregating

`account_lines_service` is **widened**, not duplicated: `account_id: int`
becomes `account_ids: Iterable[int]` and the filter becomes `.in_(...)`. It
keeps its existing `joinedload(JournalLine.entry, JournalLine.unit)`.

That gives a clean incremental path across the two issues:

- **Issue 002** (single account): `QueryAccountBalance` calls
  `account_lines_service(ctx, [account.id])`. No new service at all — the
  function that is currently written-but-unused gains its first caller.
- **Issue 003** (rollup): insert one `descendant_account_ids_service` call
  before it and pass the id list. For a leaf the id list is `[account.id]`,
  so 002's behaviour is unchanged by construction, which is exactly what
  issue 003's acceptance criterion asks for.

**The session-detachment trap does not apply to `balance`, and it is worth
being precise about why, because it looks like it should.** The use case runs
*inside* `DbTransaction.execute`, which closes the session in a `finally`
only after `use_case(ctx)` returns. Because `QueryAccountBalance` aggregates
into `UnitBalance` dataclasses before returning, no ORM object crosses the
boundary and nothing the CLI touches can lazy-load. The trap would reappear
the moment `balance`'s use case returned `list[JournalLine]` and let the CLI
read `line.unit.identifier` — which is precisely how it bit
`query_lines_by_period_service`. The `joinedload` is kept anyway, for N+1
avoidance and consistency with the sibling services, not for detachment.

**Aggregation happens in Python, in the use case, not in SQL.** The decisive
reason is that average cost is an order-dependent stateful fold (§6.4), not a
`GROUP BY` aggregate — expressing it in SQL needs a window-function chain
that is far longer and far less legible than a ten-line loop. A secondary and
honestly minor reason: SQLite stores `Numeric` as REAL, so a SQL-side
`SUM(quantity * unit_price)` accumulates in float and is then quantized to
the column's 8dp scale, while the Python sum is exact `Decimal`. Measured on
500 lines of `12345.67890123 × 3.14159265`: SQL-side differed from exact by
−1.98e-9, Python-side by zero. That is below the storage scale and would not
be a correctness problem on its own; it is recorded so the trade-off is not
rediscovered as a surprise.

`_aggregate_by_unit(lines: list[JournalLine]) -> list[UnitBalance]` is a pure
function, testable without a database.

### 6.4 Average cost — and a gap in the spec

The spec says "average cost, weighted by quantity, computed from each
contributing line's `unit_price`. Explicitly average cost, not FIFO lots."
That phrase does not say **how credit lines participate**, and the readings
diverge as soon as a sale is followed by a purchase:

Buy 10 @ 100, buy 10 @ 120, sell 5 @ 130, buy 10 @ 200 — holdings 25.

| reading | avg cost | |
|---|---|---|
| Σ(±q·p)/Σ(±q) over all lines | 142.00 | sale price contaminates cost basis |
| Σ(q·p)/Σ(q) over debits only | 140.00 | ignores that the sale consumed basis |
| moving average (chosen) | 146.00 | |

The first is plainly wrong — under it, selling at a high price *lowers* your
reported cost and selling at a loss raises it. The second silently diverges
whenever a purchase follows a sale.

**Chosen: moving-average cost**, a per-unit fold over the lines in
`(entry_date, line id)` order — which `account_lines_service` already
provides:

```
debit  q @ p :  basis += q * p                 ; quantity += q
credit q @ p :  basis -= q * (basis / quantity); quantity -= q
average      :  basis / quantity
```

A credit removes units at the *running* average, so the sale price never
enters the cost basis. This is the standard weighted-average-cost method, and
it shares its ordered-fold machinery with the FIFO work queued in
`portfolio-and-profit-reporting.md`, so the two are siblings rather than
rewrites.

Edge cases:

- **quantity reaches exactly 0** — average cost is undefined, not zero.
  `UnitBalance.average_cost` is `Decimal | None`; `None` renders as `-`.
  Reporting `0` would assert the holding cost nothing.
- **quantity goes negative** — required by issue 003, the envelope-overspend
  signal. For the base currency every line has `unit_price` 1, so basis and
  quantity stay proportional and the average stays 1 however far negative the
  envelope goes. Nothing special is needed and no error is raised: a negative
  balance is data, not a failure.
- **a credit when quantity is 0** — `basis / quantity` divides by zero. Fall
  back to the line's own `unit_price` for that step. This only arises for a
  net-short holding in a *non-base* unit, which this ledger has no other
  support for and the spec does not contemplate. It is defined so the fold
  cannot crash, and explicitly not claimed to be meaningful accounting.

**Reported to the caller as a spec gap**: the three readings above are all
consistent with the spec's sentence and give different numbers. This design
picks one.

### 6.5 CLI output

`tabulate` with `floatfmt=".2f"`, matching `entries-in-period`. One row per
unit: unit, quantity, average cost.

The base-currency total row, per the spec, is printed only when the result
holds exactly one unit and it is `BASE_CURRENCY`. That check lives in the
CLI, not the use case, because the row is a restatement of the single unit
row already present — it carries no number the use case would have to
compute. It is decoration, and decoration is the CLI's.

An empty result prints "No holdings", not an empty table and not an error
(issue 002).

---

## 7. Issue 007 — `list-accounts` as a tree

**No new service and no new use case.** `ListAccount` already returns every
account, and `Account.parent_id` is a loaded column that survives session
close (`expire_on_commit=False`). The tree is rendered in the CLI from the
flat list.

The reason this stays presentational rather than becoming a nested use-case
return type: building the nesting is a pure transform with no database
access and no ledger rule, and the two frontends want *different* shapes from
it — the CLI wants an indented string, Textual's `Tree` widget wants nodes
added parent-first. A nested intermediate would serve neither better than the
flat list already does.

One trap to state, because it is the same class of bug as the `joinedload`
one: build the tree from `parent_id`, **never** from `Account.children`.
`children` is a lazy relationship and the session is closed by the time the
CLI sees the objects.

**Rendering.** `tabulate` strips leading whitespace from cells — verified —
so space indentation is silently destroyed. Non-space connector prefixes
survive, so nesting uses `|- ` / `|  `:

```
account        type     iban
-------------  -------  ------
Cash/          asset    -
|- Eating out  expense  -
|- Groceries   expense  -
|- Unallocated asset    -
Checking       asset    DE1
```

A trailing `/` marks a parent — the filesystem convention, compact, and it
carries the meaning that matters (only unmarked accounts are postable).
Roots are accounts with `parent_id is None`; children are sorted by name at
each level. Type and IBAN stay as columns.

**`list-child-accounts`: kept, unchanged.** Issue 007 asks for a decision.
Removing it is a breaking CLI change outside the issue's remit and it costs
nothing to keep. It is however made redundant in practice by a recommended
small addition — an optional `[ACCOUNT]` argument to `list-accounts` that
roots the tree at a named account instead of at all roots, which shows the
whole subtree rather than one level. If that is added, `list-child-accounts`
becomes a candidate for removal in a later cleanup. *The optional argument is
not required by the issue; it is one `click.argument(required=False)` plus a
filter on the roots list, and is the cheapest way to answer the issue's own
question about redundancy.*

---

## 8. Issue 008 — `list-operations`

`ListOperations` and `list_operations_service` exist and are tested. The CLI
command is a direct copy of the `entries-in-period` shape.

**Ordering: `group_id DESC, id ASC`** — most recent transaction first, with
the steps inside one transaction in the order they actually happened. `id` is
autoincrement and groups are committed in order, so `group_id` is a reliable
recency key without joining `operation_groups`.

The `ORDER BY` goes into the existing `list_operations_service`, which is
currently unordered by oversight. Issue 008 forbids writing a *new* service;
this is a one-line addition to an existing one, and ordering is a persistence
concern rather than a presentation one. It does not break
`tests/test_accounts.py`, whose only assertion on this is a single-element
list.

Columns: `group`, `entity_type`, `entity_id`, `action`, via `tabulate`.
`Operation.field` and `Operation.state` are omitted — nothing writes them
today (`crud_create` sets neither), so they would be permanently empty
columns.

A group timestamp would read better than a group id, but `Operation` has no
`relationship()` to `OperationGroup` — only a `group_id` column — so showing
`created_at` needs a join and a real service change. Deferred; the obvious
follow-up if group ids prove hard to read.

**Known artefact, out of scope.** `DbTransactionContext.__init__`
unconditionally creates and flushes an `OperationGroup`, and
`DbTransaction.execute` commits it on success. Every read-only command —
`list-accounts`, `entries-in-period`, `balance`, and `list-operations`
itself — therefore leaves an empty group behind. Issue 008's "creates no
operations of its own" holds strictly, since no `Operation` rows are written
and empty groups produce no output rows, but the user will see gaps in the
`group` column. The fix is to create the group lazily on the first
`record_transaction_step`; it touches the transaction boundary that
`AGENTS.md` singles out as the codebase's most delicate seam, and does not
belong in a CLI slice.

---

## 9. The decision categories

### State and data lifecycle

Every `record` / `record-split` invocation is one `UnitOfWork`, hence one
`DbTransaction`, hence one SQLite transaction covering account lookup, unit
lookup, `validate_lines`, and the entry plus all its lines. Partial
completion is not observable: `DbTransaction.execute` either commits
everything including the `Operation` audit rows, or rolls all of it back.
This is why the new use cases are siblings of `RecordJournalEntry` rather
than callers of it — calling it would split the lookups and the posting into
two transactions.

The ledger is **append-only in this slice**: no update, no delete, no void.
Correction is a reversing entry, per the spec's Non-Goals. That makes every
recorded entry auditable and none of them reversible in place, which is the
constraint that permits `balance` to be a pure fold over history with no
snapshot or cached-balance state to invalidate. No balance is ever stored;
it is recomputed from lines on every call. For a personal ledger that is
correct and cheap, and it removes an entire class of staleness bug.

`balance`, `list-accounts` and `list-operations` are reads and commit
nothing of substance — except the empty `OperationGroup` noted in §8.

Replay: `record` deliberately is **not** idempotent (uuid reference, §5.2),
in contrast to `ImportStatement` (content-hash reference). Re-running a
`record` command posts a second entry. That is the intended behaviour for
hand entry and the reason the two paths do not share a reference scheme.

### Error propagation

Three representations, with two conversion seams:

1. **Infrastructure** — `DbTransactionContext.run` catches `IntegrityError`
   and `Exception` and returns `UniqueViolation` / `InfrastructureError`.
   Unchanged; this is the seam `AGENTS.md` records an override for.
2. **Services** — `map_err` a `UniqueViolation` into a named domain error
   where the constraint is recognised, else a generic wrapper. This slice
   adds one recognition: the journal-line unique constraint →
   `DuplicateLineInEntry` (§5.3). Services never know what a CLI is.
3. **Use cases** — return `Result[T, <union alias>]`. Two new aliases in
   `domain_errors.py`, matching the existing `QueryJournalByPeriodError` /
   `ImportStatementError` style:
   ```
   RecordEntryError = AccountNotFoundError | UnitNotFoundError | JournalError | BaseCurrencyAsCrossUnit
   BalanceError     = AccountNotFoundError | AccountError | JournalError
   ```
4. **CLI** — never inspects an error type. It prints `str(err)` in the
   existing `Failed: {res.unwrap_err()}` shape. Every domain error defines
   `__str__`, which is what makes "readable, not a traceback" (issues 001,
   006) fall out without the CLI knowing anything.

The one raised exception in the whole design is `click.BadParameter`, scoped
and justified in §5.1.

What each layer may know about the one below: the CLI knows use-case
signatures and `BASE_CURRENCY`; use cases know service signatures and domain
errors; services know the ORM. Nothing reaches past its neighbour.

### Concurrency and ownership

**Single threaded, no shared mutable state, no concurrency of any kind.** A
CLI process runs one command and exits. Stated rather than assumed because
the surrounding code has two properties that would break if it stopped being
true: `UnitOfWork` instances are single-shot (their session is closed by the
first `_run`), and `DbTransactionContext` accumulates `transaction_steps` in
a plain list with no synchronisation. Each command constructs its own
`session_local()`; nothing is shared between commands.

Mutable state ownership, such as it is: the `Session` is owned by
`DbTransaction`, which closes it; the `DbTransactionContext` is owned by the
`DbTransaction` and lives exactly as long as one use case; every value the
new code returns across a boundary (`LineInput`, `CrossUnitLine`,
`UnitBalance`, `LineSpec`) is a frozen dataclass. The one accumulator in the
new code, the running `(quantity, basis)` pair inside
`_aggregate_by_unit`, is a local in a pure function.

SQLite gives a single writer at the file level; if a TUI and a CLI ever ran
concurrently the loser would get "database is locked". That is unchanged by
this slice and is not addressed by it.

### Reuse

Used rather than reimplemented:

- `RecordJournalEntry`'s `validate_lines` — the sole home for
  balance-by-value and leaf-only posting, now reached from four callers via
  one `post_entry` helper.
- `add_journal_entry_service`, `LineSpec` — untouched apart from one added
  constraint mapping.
- `account_lines_service` — the written-but-unused function; widened by one
  parameter instead of a new sibling service, and given its first two callers.
- `get_account_by_name_service`, `get_unit_by_identifier_service`,
  `get_or_create_unit`, `account_has_children_service` — all existing.
- `ListOperations`, `list_operations_service`, `ListAccount` — existing,
  reached from the CLI for the first time.
- Click's `ParamType` machinery instead of hand-written parsers.
- `tabulate`, `click.echo`, and the `if res.is_ok: ... else: Failed:` shape
  from every existing command.

Introduced here and worth reusing next:

- `post_entry` — any future entry-creating use case (the classifier in
  `expense-classification.md`, the splitter in `expense-splitting.md`) should
  call it rather than the two calls separately.
- `descendant_account_ids_service` — needed by net worth, by subtree
  reporting, and by any future "move account" that must reject moving a node
  under its own descendant.
- `LineInput` — the name-shaped line, which is what any frontend will hand
  to a use case.

### Extension points

Deliberately few, and each is a contract that already exists rather than a
new hook:

- **`post_entry`** is the extension point for new ways of *making* entries.
  Contract: it takes `list[LineSpec]` and enforces `validate_lines`. New
  entry-shaped features add a use case that builds `LineSpec`s and calls it.
- **`UnitBalance`** is the contract between the balance fold and its
  presenters. A TUI balance view and a future net-worth report consume it
  without re-deriving quantities from lines.
- **`UnitOfWork` / `DbTransactionContext`** is the existing extension point
  for anything transactional; the new use cases plug into it unchanged.

**No plugin surface is added.** The `kohle.plugins` entry-point group exists
for statement importers and, per the vision document, will grow price
fetchers. Neither `record` nor `balance` is a plugin seat: recording is a
first-party ledger operation, and balance reads only `unit_price` already on
the lines — the price-source seam belongs to `price-fetcher-plugin.md`, not
here.

**No abstraction is introduced for future FIFO.** The moving-average fold is
written concretely. FIFO in `portfolio-and-profit-reporting.md` will be a
second concrete fold over the same ordered line sequence; whether they share
a shape becomes answerable once both exist, and inventing a `CostMethod`
interface now would be an abstraction with one implementation.

### Build vs. buy

- **Recursive descendants** — buy. SQLite's `WITH RECURSIVE` (3.45, present)
  via SQLAlchemy's `cte(recursive=True)` (2.0.46, present). Evaluated writing
  the walk in Python and rejected in §6.1.
- **Tree storage** — buy nothing, build nothing. `parent_id` adjacency is
  already in the schema and adequate. A closure table or `sqlalchemy-mptt`
  would each demand a migration and write-path maintenance for a ten-node
  tree.
- **Decimal parsing / date parsing / choice validation at the CLI** — buy.
  Click's `ParamType`, `DateTime`, `Choice`. The one build is a ~6-line
  `DecimalParamType`, because Click 8.3 ships no `Decimal` type (verified)
  and `float` is not an acceptable substitute in a money ledger.
- **Table rendering** — buy, `tabulate`, already a dependency and already
  the house style. `rich` is also already a dependency and renders nicer
  tables, but mixing two table renderers across sibling commands is worse
  than a plain one used consistently.
- **Average-cost computation** — build. Evaluated: `pandas` is already a
  dependency and could express a groupby, but not the order-dependent
  running-average fold without an `apply` that is longer and slower than the
  loop; and a full accounting library (`beancount`, `ledger`) is not a
  component that could be dropped into this codebase — it *is* a different
  ledger, with its own storage model, and adopting one would delete this
  project rather than extend it.
- **UUID references** — buy, `uuid.uuid4` from the stdlib.

### Abstractions introduced

Each with the problem forcing it. Anything without one is not here.

| Abstraction | Forcing problem |
|---|---|
| `LineInput` | The CLI holds *names*; `LineSpec` requires *ids*; only services may resolve names. Something must cross that boundary carrying a line. |
| `CrossUnitLine` | Unit, price and side are mutually dependent. As three optional parameters, "price without unit" is representable at the use-case boundary and must be re-rejected there; as one optional value it cannot be constructed. |
| `UnitBalance` | The session closes before the CLI reads the result, so a detached value type is required; and it is the contract a second frontend consumes. |
| `post_entry` | Makes "`validate_lines` is called exactly once" a structural fact with one call site rather than a convention repeated at four. |
| `descendant_account_ids_service` | The subtree query is over `Account` and must stay in the account service; it is also the only place the `UNION`/id-only termination property lives, and isolating it makes that property testable on its own. |
| `DecimalParamType` | Click has no `Decimal` type and `float` corrupts money. |

Explicitly **not** introduced, having no forcing problem:

- A `Side` enum. `is_debit: bool` is the vocabulary `JournalLine` and
  `LineSpec` already use; a parallel enum would mean two representations of
  one bit.
- A `BalanceReport` wrapper around `list[UnitBalance]`. The list is the
  report.
- A `CostMethod` / `Valuation` interface. One implementation.
- A repository layer over the services. The services *are* that layer.
- Any cycle-detection error type (§6.2) or pre-check for the journal-line
  unique constraint (§5.3) — both are checks for conditions already handled
  elsewhere.

### Alternatives rejected

Consolidated; each is argued where it arises.

| Rejected | Where | Short reason |
|---|---|---|
| `--to` always carries the non-base unit | §2.3 | cannot express a sale; silently wrong if attempted |
| `--unit-side from\|to` | §2.3 | direction stated twice, nothing enforces agreement; needs a default |
| `--unit-account ACCOUNT` | §2.3 | catches typos only, not the actual failure mode |
| Infer direction from `AccountType` | §2.3 | both sides are assets in every case that matters |
| Separate `buy` / `sell` commands | §2.3 | fails the spec's "through `record`"; relocates rather than removes the hardcoded side |
| Ignoring, or honouring, `--price` on a base-currency unit | §3 | honouring corrupts EUR average cost permanently; ignoring discards user input silently |
| A `--own` flag on `balance` | §4 | output is either identical to the default or provably empty, except in one state the user must already suspect |
| New use cases wrapping `RecordJournalEntry` | §5.2 | two sessions, two transactions; lookups would commit separately from the posting |
| Folding `ImportStatement` into `post_entry` | §5.2 | behaviour-neutral refactor of tested code, not feature work |
| Passing date/decimal strings to use cases | §5.1 | forces a typed frontend to stringify values for a parser to re-parse |
| Pre-checking duplicate lines in `validate_lines` | §5.3 | the DB constraint already enforces it; a pre-check cannot name the colliding line either |
| Application-side / recursive-function tree walk | §6.1 | O(depth) queries, Python recursion limit, stack blowout on a cycle |
| Closure table / materialized path / nested sets | §6.1 | migration plus write-path maintenance for a ten-node tree |
| SQL-side `GROUP BY` aggregation | §6.3 | average cost is an ordered stateful fold, not an aggregate; float accumulation is a secondary cost |
| `Σ(±q·p)/Σ(±q)` over all lines for average cost | §6.4 | sale price contaminates cost basis; selling high lowers reported cost |
| Debits-only average cost | §6.4 | diverges whenever a purchase follows a sale |
| A nested tree type returned by `ListAccount` | §7 | pure transform, no DB access, and the two frontends want different shapes |
| Space indentation in the account tree | §7 | `tabulate` strips leading whitespace (verified) |
| Joining `operation_groups` for a timestamp | §8 | needs a relationship that does not exist; deferred |

---

## 10. Issue mapping

| Issue | Lands |
|---|---|
| 001 record base-currency entry | `record` with no unit flags; `RecordSimpleEntry` with `cross=None`; `post_entry`; `LineInput` |
| 002 balance single account | `QueryAccountBalance` + `UnitBalance` + `_aggregate_by_unit`, calling `account_lines_service(ctx, [id])` (widened signature) |
| 003 balance subtree rollup | `descendant_account_ids_service` (recursive CTE, §6.1–6.2); one extra call in `QueryAccountBalance` |
| 004 cross-unit purchase and sale | `--from-unit/--from-price` / `--to-unit/--to-price`; `CrossUnitLine`; `BaseCurrencyAsCrossUnit` |
| 005 average cost | the moving-average fold in `_aggregate_by_unit` (§6.4) |
| 006 record-split | `--line` callback; `RecordSplitEntry`; `DuplicateLineInEntry` mapping |
| 007 list-accounts as tree | CLI rendering only; no service, no use case |
| 008 operation audit trail | `list-operations` command; `ORDER BY` on the existing service |

Dependency order matches the issues: 001 → 004 → 006 on the write side,
002 → 003 → 005 on the read side, with 007 and 008 independent.

---

## 11. Testing notes

Extends the existing pattern — use-case tests against the `session` fixture,
asserting on `Result` and on domain error types.

- `_aggregate_by_unit` and the `--line` parser are **pure functions** and get
  direct unit tests with no fixture. The average-cost cases from §6.4 —
  including buy/sell/buy, quantity to exactly zero, and quantity going
  negative — belong here, since they are where the spec was underspecified.
- `descendant_account_ids_service` gets its own tests: deep chain, wide tree,
  leaf-returns-itself, and a **cycle test** built by setting `parent_id`
  directly on committed rows. That last one is the regression guard for the
  `UNION`/id-only property in §6.2, and without it a later "add a depth
  column" change turns `balance` into a hang with no failing test.
- The cash-envelope scenario (spec Goals, issue 003) is one end-to-end
  use-case test: build the tree, withdraw, allocate, spend, overspend, assert
  `balance Cash` rolls up and `balance Groceries` goes negative.

**Testability gap, flagged not solved.** Every CLI command constructs
`session_local()` inline, which binds to the real `kohle.db`. A
`CliRunner`-based test would therefore write to the user's ledger. This slice
does not fix that — injecting the session factory is a change to every
existing command and belongs in its own piece of work — so CLI coverage here
is limited to the pure parsers, and the command bodies stay thin enough that
what is left untested is a `tabulate` call and an f-string.
