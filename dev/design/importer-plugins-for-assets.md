# Design: Importer plugins for asset statements

Spec: `dev/specs/importer-plugins-for-assets.md` (frozen)
Issues: `dev/issues/025`–`028`

Layering per `AGENTS.md` stays `app -> use_cases -> services ->
infrastructure/domain`. Only services touch a `Session`. Functions return
`Result[T, E]`; domain errors are `Exception` subclasses used as values.

> **Status: blocked on one spec revision.** The Deutsche Bank CSV has no
> native per-row reference (§2), and the spec forbids the only kind of key
> that format can supply. Everything else here is settled and does not depend
> on how that is resolved — but issue 025 cannot be finished, and 026–028
> depend on 025, until the user revises the spec. §2.4 lists the options.

---

## 1. Summary of the shape

| File | Change |
|---|---|
| `kohle/plugin/importer_plugin.py` | `CashRow`, `SecurityRow`, `StatementRow`; `import_statement` returns `Result[list[StatementRow], ImportError]`; `StatementUnreadable`; pandas import and the DataFrame docstring go |
| `kohle/use_cases/journal.py` | `ImportStatement.execute(cash_account_name, rows, instrument_account_name=None)`; new pure `validate_statement`; new `_cross_unit_lines`, shared with `RecordSimpleEntry`; `_optional_str` loses its pandas half; `validate_df_schema` and the pandas import deleted |
| `kohle/domain/domain_errors.py` | `StatementError` family; `UnknownInstruments`, `NotASecurityUnit` under `UnitError`; `ImportStatementError` swaps `DataframeValidationError` for `StatementError`; `DataframeMissingColumn` / `DataframeColumnTypeMismatch` deleted; `NoClassificationForEntry.__str__` reworded |
| `kohle/app/plugins/kohle_deutsche_bank_importer.py` | emits `CashRow`s; catches unreadable input; every error gets `__str__`; **row reference source blocked (§2)** |
| `kohle/app/plugins/kohle_synthetic_broker_importer.py` | **new** — the synthetic broker CSV (§7) |
| `kohle/app/cli/cli.py` | `import-statement PLUGIN CASH_ACCOUNT [INSTRUMENT_ACCOUNT] STATEMENT_FILE` |
| `pyproject.toml` | second `kohle.plugins` entry point |
| `tests/fixtures/` | **new** — `synthetic_broker.csv`, and a hand-built Deutsche Bank statement (§12) |
| `README.md` | plugin contract section rewritten |
| `alembic/versions/` | **nothing** — no schema change (§8) |

**No new service, no new table, no new use case.** Every read and write the
asset path needs already exists: `get_account_by_name_service`,
`get_unit_by_identifier_service`, `existing_references_service`,
`post_entry`, `add_classification_service`. The feature is a contract change,
one new branch in one loop, and one new plugin.

**Import direction.** `use_cases/journal.py` imports the row types from
`kohle/plugin/importer_plugin.py`. That is with the grain only because the
contract module is a leaf: it imports nothing from kohle but `kohle.core`.
It must stay that way — the moment it imports from `services` (for example to
reuse `Counterparty`, §3.2), every third-party plugin depends on the services
layer and the layering inverts.

---

## 2. Blocking finding: the Deutsche Bank statement has no native per-row reference

### 2.1 What was inspected

- The plugin's own header grammar, `expected_columns` in
  `kohle_deutsche_bank_importer.py` — the parser rejects any file whose
  header is not exactly these 18 columns, so this list is the whole format:
  `Booking date`, `Value date`, `Transaction Type`, `Beneficiary /
  Originator`, `Payment Details`, `IBAN / Account Number`, `BIC`, `Customer
  Reference`, `Mandate Reference`, `Creditor ID`, `Compensation amount`,
  `Original Amount`, `Ultimate creditor`, `Number of transactions`, `Number
  of cheques`, `Debit`, `Credit`, `Currency`.
- **Test fixtures: there are none.** No Deutsche Bank statement exists
  anywhere in the repository, and no test exercises the plugin — the "import
  tests" the spec refers to feed hand-built DataFrames straight into
  `ImportStatement`. `archive/deutsche_bank_parser.py` drops both reference
  columns too. Nothing in the repo has ever read these two columns.

### 2.2 Why neither candidate column qualifies

There is **no bank-assigned, per-booking identifier among the 18 columns.**
The two candidates are references *someone else* assigned, for a different
purpose:

- **`Customer Reference`** is the SEPA end-to-end id, set by whoever
  *initiated* the payment. It exists only for SEPA transfers and direct
  debits — a card payment or an ATM withdrawal has none, so it is blank on
  exactly the rows that make up most of a current-account statement. Where a
  payer did not supply one, SEPA's placeholder is the literal `NOTPROVIDED`,
  so even a non-blank cell is not necessarily an identifier. Where it is
  real, its uniqueness is only as good as the counterparty's discipline; the
  bank does not enforce it.
- **`Mandate Reference`** identifies a direct-debit *mandate*. Every
  collection under one mandate carries the same value — a monthly gym
  membership has the same mandate reference every month — so it is
  non-unique by definition, and blank on everything that is not a direct
  debit.

Under the spec as written, a row whose reference is absent rejects the whole
import (Goals, bullet 6). Using `Customer Reference` would reject every
statement that contains a single card payment. Using `Mandate Reference`
would reject every statement with two months of the same direct debit, as a
within-file duplicate. Neither is usable. Any composite of columns
(date + amount + IBAN + …) is a content-derived key, which is precisely the
fallback the spec's third Non-Goal rules out.

**This rests on the column list and on SEPA semantics, not on a real export**,
because no export is in the repo. The user can confirm it in a minute by
opening any recent statement: if `Customer Reference` is blank on the card
payment rows, the finding stands.

### 2.3 What it blocks and what it doesn't

`CashRow.reference` is a required field (§3.2), and issue 025 migrates the
Deutsche Bank plugin onto `CashRow`. The plugin has nothing to put in that
field that the spec allows. So **025 cannot be completed** — and per the
global "no half-finished implementations" rule it should not land with a
placeholder. 026–028 depend on 025.

Everything else in this document is independent of the resolution. Options A
and C below change only the Deutsche Bank plugin; option D deletes it. The
contract, the use case, the CLI, the broker plugin and the tests are the same
under all three.

The one thing that *can* start now is the characterisation test for the
Deutsche Bank plugin (§12), which records today's ledger output against the
current code and does not involve references at all.

### 2.4 Options for the spec revision (the user's call)

| | Option | What changes in the spec | Cost |
|---|---|---|---|
| **A** | **The plugin derives the reference; the use case never does.** The contract keeps `reference: str` mandatory. The Deutsche Bank plugin computes a row's reference from its own content (today's `date\|amount\|description` hash, minus the account id, since the use case now scopes). | The third Non-Goal is narrowed from "no content-hash fallback" to "no fallback in the contract or the use case; a plugin whose format has no reference may derive one, and owns its collision risk". | Smallest. Behaviour is unchanged: two rows identical in date, amount and description already fail today's import (the second insert hits `uq_journal_entry_reference`), and under this design they fail it earlier and with a better message (`DuplicateReferenceInStatement`). The card-payment timestamp in `Payment Details` keeps real collisions rare. |
| **B** | Use `Customer Reference`, reject rows without one. | None. | **Not viable** (§2.2): rejects any statement containing a card payment. Listed so it is not re-proposed. |
| **C** | **Switch the Deutsche Bank plugin to a format with a bank-assigned entry reference**, such as CAMT.053 (`AcctSvcrRef`). | The Goal "the existing Deutsche Bank plugin … pass[es] against the migrated contract with no change in resulting ledger rows" becomes "a Deutsche Bank CAMT plugin replaces the CSV plugin". | A new parser. Also, `AcctSvcrRef` is optional in the CAMT schema, so whether Deutsche Bank fills it for retail accounts, and whether that export is offered to private customers at all, has to be checked against a real file before this is chosen. |
| **D** | **Drop the Deutsche Bank CSV plugin**: the spec's own Non-Goal ("plugins for formats with no native per-row reference") read literally. | The regression-case Goal is deleted. | The user loses bank-statement import until a replacement exists. |
| ~~E~~ | `reference: str \| None`, with the use case hashing when it is absent. | — | **Excluded by the spec**: "do not generalise a fallback mechanism in advance". Listed so it is not re-proposed. |

**Recommendation: A.** It keeps the contract uniform (every row of every
plugin carries a mandatory reference), keeps the use case free of any
fallback logic, puts the content-derived key in the one plugin whose format
forces it, and changes no observable behaviour. The question it leaves open
is the one the Non-Goal was guarding: whether to allow content-derived keys
*anywhere*. That is a product decision, and it belongs to the user.

---

## 3. The row types

### 3.1 Placement

In `kohle/plugin/importer_plugin.py`, per the spec, beside
`StatementImporterPlugin`. They are the contract: a plugin author imports
them from there and nowhere else.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CashRow:
    entry_date: date
    reference: str
    description: str
    amount: Decimal                  # base currency, signed; negative is money leaving the account
    counterparty_name: str | None
    counterparty_iban: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SecurityRow:
    entry_date: date
    reference: str
    description: str
    instrument_identifier: str       # matches Unit.identifier, e.g. an ISIN
    quantity: Decimal                # signed; positive is units into the instrument account (a buy)
    unit_price: Decimal              # base currency per unit at the time of the trade


StatementRow = CashRow | SecurityRow
```

- **`frozen`, `slots`:** house style (`LineSpec`, `Counterparty`,
  `CrossUnitLine`). Rows cross from plugin code into the use case and nothing
  may mutate them on the way.
- **`kw_only`** has a specific forcing problem. `CashRow` has four `str`
  fields in a row (`reference`, `description`, `counterparty_name`,
  `counterparty_iban`) and `SecurityRow` has three. Built positionally,
  transposing any two type-checks and silently stores the wrong field. This
  is the same transposition hazard `Counterparty` was introduced to remove
  (`expense-classification.md` §3.2), solved here without importing
  `Counterparty` into the contract (§3.2).
- **No defaults on any field**, including the counterparty pair. Issue 013
  established that omitting a counterparty must not be silent, and enforced
  it by requiring the DataFrame column to be *present and empty*. The typed
  version of that rule is a required field: a plugin with no counterparty
  data writes `counterparty_iban=None` explicitly, as a visible one-line
  statement, and forgetting it is a `TypeError` at construction and a mypy
  error at the author's desk.
- **`entry_date`, not `date`.** It matches `JournalEntry.entry_date` and
  `post_entry`'s parameter, and avoids a field that shadows the `date` type in
  the same class body.
- **`Decimal`, not `float`.** The `float` amount was a DataFrame dtype
  artefact. `ImportStatement` immediately did `Decimal(str(row["amount"]))` to
  undo it.

### 3.2 `CashRow`

This is today's five-column frame as one value, plus `reference`. It means
exactly what the frame meant: quantity in the base currency at price 1,
signed, with the counterparty pair and free text.

**The counterparty is two fields, not a `Counterparty`.** `Counterparty`
lives in `services/journal_services.py`. Using it in the contract would make
`kohle/plugin` import from `services`, and so make every plugin depend on the
services layer (§1). `kw_only` gives the transposition safety that
`Counterparty` exists for. The use case builds the `Counterparty` value
itself, from the row, exactly as it builds it from a DataFrame record today.

### 3.3 `SecurityRow`, and what "non-optional price" means at runtime

The spec makes a security row without a price a type error. That has two
halves, and the design delivers both:

1. **Static:** `unit_price` is a required, non-`Optional` field.
   `SecurityRow(..., quantity=q)` with no `unit_price` raises `TypeError` on
   construction and is flagged by mypy. This is the "at the plugin author's
   desk" half.
2. **Runtime, before any write:** dataclasses do not check types, so
   `SecurityRow(..., unit_price=None)` constructs fine. That is the shape a
   careless plugin actually produces when an empty CSV cell maps to `None`.
   `validate_statement` (§4.3) rejects it before the first database call.
   That is the spec's "rejected before any write", and the test suite holds
   it (§12).

**Signed quantity rather than a side enum.** `CashRow.amount` is already
signed, with the sign meaning "into or out of the account this row is
about". `SecurityRow.quantity` follows the same convention, where the account
in question is the instrument account. One rule across the contract, and
the synthetic plugin maps `sell` to a negative quantity (§7).

**No cash amount on a security row.** The cash leg is `|quantity| ×
unit_price` (§4.6). A separate cash field would make an unbalanced trade
expressible, and the only thing that would make it differ from `quantity ×
price` is fees, which the spec's second Non-Goal leaves out of v1. The
synthetic format agrees: buy and sell rows carry no `amount` (issue 028). See
§13.6 for what a real broker format reopens.

### 3.4 The contract method and plugin errors

```python
class StatementImporterPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def import_statement(self, statement_path: str) -> Result[list[StatementRow], ImportError]: ...
```

- **Rows come back in statement order, one per statement line the plugin
  maps.** The use case numbers them from 1 in that order when it reports a
  malformed row.
- **The plugin owns reference uniqueness across its own row types.** A
  broker whose trade ids and dividend ids come from separate sequences must
  make them distinct, for example by prefixing. The use case checks
  uniqueness across the whole returned list (§4.3) and does not know which
  sequence a reference came from.
- **`import_statement` holds no state between calls.** The Deutsche Bank
  plugin already builds a fresh `StatementParser` per call. The contract
  docstring says so, because a future TUI would keep one plugin instance
  alive across imports.
- **`StatementUnreadable(path, reason)`** is new and lives in the contract
  module, because both plugins need it and the spec requires an unreadable
  file to produce a named error. A plugin converts `OSError` and
  `UnicodeDecodeError` from reading the file into it — explicit types, at the
  one place the file is read.
- **Every plugin error defines `__str__`.** The CLI prints `str(err)`, and
  today the Deutsche Bank plugin's `MissingSectionError`,
  `InvalidStructureError` and `CsvError` print an empty string, because their
  `__init__` never passes a message to `Exception`. That is the current
  failure of issue 025's "surfaces as a named error" criterion (§13.7).
- `ImportError` keeps its name. It shadows the builtin, which is a
  pre-existing wart. Renaming it would touch every plugin for no requirement
  in this feature, so that is recorded rather than done.

`pandas` leaves the contract module. Whether a plugin uses pandas internally
is its own business (spec, Open Questions); the Deutsche Bank plugin still
does.

---

## 4. `ImportStatement`

### 4.1 Signature

```python
class ImportStatement(UnitOfWork[int, ImportStatementError]):
    def execute(
        self,
        cash_account_name: str,
        rows: Sequence[StatementRow],
        instrument_account_name: str | None = None,
    ) -> Result[int, ImportStatementError]: ...
```

- **`Sequence`, not `Iterable`:** the rows are read twice, once by
  validation and once by the loop.
- **`instrument_account_name` is last and defaults to `None`**, so every
  existing cash-only call site (`execute("Checking", rows)`) changes only its
  second argument, from a frame to a list.
- Returns the number of entries posted, as today.

### 4.2 The flow, in order

The order is deliberate: every check that can be made without the database
comes before the first read, and every read that can fail comes before the
first write. Atomicity does not depend on this ordering, because the
transaction rolls back regardless (§9). The ordering is what makes a rejected
import name the right problem, and it makes "a re-import writes nothing"
hold structurally rather than by luck.

1. **`validate_statement(rows)`** — pure. Malformed row or duplicate
   reference: `Err`. (§4.3)
2. **Instrument account required?** If any row is a `SecurityRow` and
   `instrument_account_name is None`: `Err(MissingInstrumentAccount())`. This
   is decided by the statement's shape, not by what the ledger already holds,
   so re-importing a broker file without the instrument account is refused
   even when every trade in it was already imported. Same input, same
   requirement.
3. **Resolve the cash account**, and the instrument account if one was
   named, through `get_account_by_name_service`: `AccountNotFoundError`. A
   named instrument account is resolved even when the statement has no
   trades, because the user typed it and a typo should fail.
4. **Scope and dedup.** Build each row's scoped reference once (§4.4) and
   pass them all to `existing_references_service`. The rows still to post are
   the ones whose scoped reference is not already present.
5. **Nothing new → `Ok(0)`, before any write.** Today the EUR unit and the
   two buckets are get-or-created *before* this check. On any ledger that
   has seen an import they already exist, so the reordering changes no
   outcome. But now a re-import makes no write call at all, and so (with
   group creation being lazy) leaves no `OperationGroup` behind, whatever
   state the ledger is in.
6. **Resolve instruments** for the new security rows (§4.7):
   `UnknownInstruments` / `NotASecurityUnit`.
7. **Get-or-create EUR**, the two buckets, and **compile the rules**: today's
   code, unchanged.
8. **The loop**, branching on row type:

```python
for row, reference in new_rows:
    match row:
        case CashRow():
            ...  # today's body, §4.5
        case SecurityRow():
            ...  # §4.6
        case _:
            assert_never(row)
```

`assert_never` is a static exhaustiveness check, not runtime defence. If a
third row type is ever added to `StatementRow`, mypy fails here until it is
handled, instead of the new type silently falling into a cash `else`.

### 4.3 `validate_statement`

```python
def validate_statement(rows: Sequence[StatementRow]) -> StatementError | None
```

A pure function in `journal.py`, beside `validate_lines`, which it mirrors
(`-> SomeError | None`). It makes one pass, in row order, and returns the
first problem:

| Check | Applies to | Error |
|---|---|---|
| `reference` is `None`, empty, or whitespace | every row | `MalformedStatementRow(n, "reference", "is empty")` |
| `reference.strip()` already seen in this list | every row | `DuplicateReferenceInStatement(ref, first_n, n)` |
| `instrument_identifier` empty or whitespace | `SecurityRow` | `MalformedStatementRow(n, "instrument_identifier", "is empty")` |
| `unit_price` is `None` / not finite / `<= 0` | `SecurityRow` | `MalformedStatementRow(n, "unit_price", …)` |
| `quantity` is `None` / not finite / `== 0` | `SecurityRow` | `MalformedStatementRow(n, "quantity", …)` |

**What it checks, and why exactly these.** Each check targets a value whose
failure would otherwise be *silent*, or which the spec explicitly names:

- An absent or within-file duplicate reference: the spec says it is a
  malformed statement.
- A `None` price: the spec's named test.
- A zero or negative price: it balances, posts, and records a cost basis of
  zero or less. That is the silent-wrong-profit failure the spec exists to
  prevent.
- A non-finite price (`Decimal("NaN")`, which is what `Decimal(str(nan))`
  gives a plugin that read an empty pandas cell): it fails much later, as a
  baffling `UnbalancedEntry` of `NaN` against `NaN`.
- A zero quantity: it posts a meaningless zero-value trade.
- An empty identifier: it would otherwise show up as an unknown instrument
  `''`.

**Cash rows get only the reference check.** The spec requires a cash row to
keep today's behaviour exactly, and today's path validates nothing about the
amount. A `None` cash amount already fails loudly (a `TypeError`, rolled back
at the `BLE001` seam), so it is not one of the silent cases.

**`identifier` is not stripped; `reference` is.** A reference that drifts
between plugin versions (`" T1"` becoming `"T1"`) fails *silently*: the row
re-imports as a new fact and cash is double-counted. Stripping prevents
that, and costs nothing. An identifier that does not match fails *loudly*,
as `UnknownInstruments` with the `repr` showing the whitespace, so leaving it
alone hides nothing.

**First problem, not all problems.** A malformed row is a plugin bug, and
one is enough to send the author back. Unknown instruments are different:
they are the user's to fix, so §4.7 collects them all.

### 4.4 Reference scoping

```
scoped reference = f"{cash_account.id}:{row.reference.strip()}"
```

- **Scoped by the cash account, for every row type.** The cash account is
  the one leg every row touches: a cash row's own account, and a trade's
  cash leg. The alternative, scoping a trade by the instrument account, has
  a concrete failure. Re-import a broker file naming a different instrument
  account, and every trade imports again, double-posting the cash leg into
  the same cash account. Scoped by the cash account, that re-import is
  correctly a no-op, because it is the same facts on the same money. The
  spec's "same reference on two different accounts is two different facts"
  holds through the cash account. For the Deutsche Bank path there is only
  one account, so nothing changes.
- **A readable string, not a hash.** Today's hash existed because its input
  *was* the row content. Now the input is an identifier, and hashing it
  would only make `journal_entries.reference` unreadable when someone opens
  the database to ask where an entry came from.
- **It cannot collide with any other reference in the table.** `record` and
  `record-split` use `uuid4().hex` (32 hex characters, no `:`), and the old
  import hash was 64 hex characters with no `:`. Account ids are digits, so
  the first `:` is unambiguous even when a native reference itself contains
  colons.
- **Computed once per row**, into the `(row, reference)` pairs that both the
  dedup lookup and `post_entry` consume. If the two derivations ever drifted
  apart, rows would silently re-import, so there is one derivation site and
  no helper function.
- `JournalEntry.reference` remains the dedup column, unique, as the spec
  says. No schema change (§8).

**Dedup is by identity, not by content.** If a broker corrects a trade and
reuses its reference, the corrected row is skipped as already imported. That
is what "deduplicated by the native reference" means, and it is stated here
so it reads as a consequence and not a bug.

### 4.5 The cash branch

Today's loop body (`journal.py:379-429`), with three mechanical changes and
no change to behaviour:

- `row["amount"]` → `row.amount`, already a `Decimal`, so
  `Decimal(str(...))` goes.
- `row["description"]` → `row.description`; `row["date"]` →
  `row.entry_date`; the scoped `reference` comes from the pair.
- `_optional_str(row["counterparty_name"])` keeps its call, but
  `_optional_str` becomes `str | None -> str | None` (strip; blank becomes
  `None`). The `pd.isna` half moves into the Deutsche Bank plugin, which is
  now the only place a `pd.NA` can exist. The blank-to-`None` half stays in
  the use case because it enforces a *ledger* rule — `''` must never be
  stored, since a rule could match it (`expense-classification.md` §3.1) —
  and that rule has to hold for any plugin, not only the one that happens to
  normalise.

Rule matching, the `unclassified-income` / `unclassified-expense` fallback,
the leaf-only failure for a rule target that has since gained a child, and
the classification record on both paths are all untouched. A broker's
dividend, interest or refund row takes this branch with no knowledge that it
came from a broker.

### 4.6 The security branch and `_cross_unit_lines`

```python
case SecurityRow():
    lines = _cross_unit_lines(
        holding_account_id=instrument_account.id,
        holding_unit_id=units[row.instrument_identifier],
        quantity=abs(row.quantity),
        unit_price=row.unit_price,
        cash_account_id=cash_account.id,
        cash_unit_id=eur_id,
        into_holding=row.quantity > 0,
    )
    entry_res = post_entry(ctx, row.entry_date, reference, row.description, lines)
```

| | Instrument account | Cash account |
|---|---|---|
| Buy (`quantity > 0`) | **debit** `q` units @ `p` | **credit** `q × p` EUR @ 1 |
| Sell (`quantity < 0`) | **credit** `q` units @ `p` | **debit** `q × p` EUR @ 1 |

- **No rule matching, no classification row, no counterparty.** Both legs
  are named on the CLI (spec). `post_entry` gets `counterparty=None`, so both
  counterparty columns are `NULL`, as for `record`.
- **The sale is priced at the sale price**, the same shape
  `record --from-unit` already produces. `aggregate_by_unit`'s moving-average
  fold relieves the position at average cost, and a later FIFO replay has the
  price it needs on every line.
- **Balanced by construction**, and `post_entry` still validates it, along
  with the leaf-only rule for both accounts. So a non-postable instrument or
  cash account fails here, through `PostingToNonLeafAccount`, exactly as a
  non-postable cash account fails today.

**`_cross_unit_lines` is factored out of `RecordSimpleEntry`'s cross-unit
branch** (`journal.py:230-238`), which builds exactly this two-line shape:
the non-base leg at its price, the base leg at `quantity × price` and price
1. **Forcing problem:** a hand-entered trade (`record`) and an imported trade
must be the *same shape* for the cost fold, and later profit reporting, to
treat them identically. Two copies of four lines are two definitions of
"what a trade looks like", and nothing would keep them in agreement.
Keyword-only, because it takes four `int` ids and transposing two of them
type-checks.

### 4.7 Instrument resolution

Before any write, for the **distinct** `instrument_identifier`s among the new
security rows: one `get_unit_by_identifier_service` call per identifier,
building `units: dict[str, int]`.

- **`UnitNotFoundError` is collected, not returned.** After the pass, if any
  identifiers were missing, the result is
  `Err(UnknownInstruments(sorted(missing)))`. Its message names every one and
  gives the real command: `kohle-cli add-unit <identifier> <name>` (kind
  defaults to `security`; §13.4). A broker statement introducing three new
  holdings costs one round trip, not three.
- **Any other `UnitError`** (an infrastructure failure) propagates at once.
- **A unit whose kind is not `security`** gives
  `Err(NotASecurityUnit(identifier, kind))`. The spec defines instrument
  identity as `Unit.identifier` with `UnitKind.security`. A trade on `EUR`
  or on a commodity unit would post, balance, and mean nothing: the
  silent-wrong-number class again. It is one comparison on a value already
  loaded.
- **Only new rows are resolved.** An already-imported trade resolved when it
  was imported, and units are never deleted.
- **Never created.** No `get_or_create_unit` for instruments (spec). The base
  currency is still get-or-created, as today and for the same reason
  `RecordSplitEntry` gives: `BASE_CURRENCY` is a constant the user never
  types, so creating it cannot hide a typo.

---

## 5. The CLI

```
kohle-cli import-statement PLUGIN_NAME CASH_ACCOUNT [INSTRUMENT_ACCOUNT] STATEMENT_FILE
```

```python
@click.argument("plugin_name")
@click.argument("cash_account")
@click.argument("instrument_account", nargs=-1, metavar="[INSTRUMENT_ACCOUNT]")
@click.argument("statement_file", type=click.Path(exists=True))
```

- **The spec's four-positional form works, and the existing three-positional
  form keeps working** for cash-only statements such as Deutsche Bank. Click
  takes a `nargs=-1` argument in the middle and fills the arguments after it
  from the end. This was verified against Click 8.3.1 in the project venv:
  `p Checking f.csv` gives `()`, `p Cash Depot f.csv` gives `('Depot',)`, and
  `p f.csv` is a usage error naming `STATEMENT_FILE`. `metavar` makes the help
  text read `[INSTRUMENT_ACCOUNT]` without Click's `...`.
- **More than one instrument account is rejected** by the command with
  `click.BadParameter` before any plugin runs. `nargs=-1` accepts several,
  so the command has to refuse them.
- **The plugin runs before a session exists**, as today: a plugin failure
  exits non-zero with `str(err)`, and no transaction is ever opened.
- Output is unchanged: `Import succeded, N entries imported`. Issue 026's
  "reports zero entries imported" is this line with `N = 0`.

---

## 6. The Deutsche Bank plugin migration (issue 025)

The pandas pipeline stays, as the plugin's internal business. Changes:

1. **The tail of the pipeline turns records into `CashRow`s** instead of
   returning the frame: `entry_date` from the existing `date` column (the
   card-payment timestamp extraction is unchanged), `amount` straight from
   `parse_amount` (a `Decimal`; the `astype({"amount": float})` goes),
   `description`, and the counterparty pair passed through a plugin-local
   `NA → None` helper (the half of `_optional_str` that leaves the use case).
2. **`reference`: blocked (§2).** Under option A it is a digest of the row's
   date, amount and description, computed here.
3. **Unreadable input becomes a named error.** The `open()` call is wrapped
   to catch `OSError` and `UnicodeDecodeError`, returning
   `StatementUnreadable`. Today it raises out of the plugin into a traceback.
4. **`__str__` on `MissingSectionError`, `InvalidStructureError`, `CsvError`**
   (and `MissingFieldError` keeps its own).

**An encoding question, recorded and not changed.** The plugin passes
`encoding='ISO-8859-1'` to `read_csv`, but on a `StringIO` that argument does
nothing. The file itself is opened with the locale default (UTF-8 here). The
archived original parser read the raw file as ISO-8859-1, so a Latin-1
export with an umlaut probably raises `UnicodeDecodeError` today. Switching
the `open()` to ISO-8859-1 would fix that, but it would also turn umlauts
into mojibake if the real export is UTF-8. Without a real export there is no
way to tell, and the Goal says "no change in resulting ledger rows". So this
design does only step 3: today's crash becomes a named error, and the
encoding is a question for whoever holds a real statement.

Out of scope and left alone: the broad `except Exception` in `_extract_table`
(pre-existing, outside the two sanctioned `BLE001` seams), and the
`DeustcheBank` spelling in the class name, which the entry point references.

---

## 7. The synthetic broker plugin and CSV format (issue 028)

`kohle/app/plugins/kohle_synthetic_broker_importer.py`, class
`SyntheticBrokerStatementImporter`, plugin name `kohle-synthetic-broker`,
registered in `pyproject.toml` under `[project.entry-points."kohle.plugins"]`.
The naming follows the Deutsche Bank plugin.

### 7.1 The format

- UTF-8, comma-delimited, `.` as the decimal point, no thousands separators,
  no currency symbols.
- **The first line is exactly** `date,reference,type,isin,quantity,price,amount`,
  in that order. Anything else gives `UnexpectedHeader(found)`. There is no
  preamble and no trailer. Fully blank lines are skipped, which is the stdlib
  `csv` reader's default.
- One data line per statement row, emitted in file order.

| Column | `buy` / `sell` | `dividend` |
|---|---|---|
| `date` | required, ISO `YYYY-MM-DD` | required, ISO `YYYY-MM-DD` |
| `reference` | passed through | passed through |
| `type` | `buy` or `sell` (exact, lowercase) | `dividend` |
| `isin` | required, non-empty | optional — used only in the description |
| `quantity` | required, decimal, **> 0** | must be empty |
| `price` | required, decimal, **> 0**, EUR per unit | must be empty |
| `amount` | must be empty | required, decimal, signed EUR (positive is money in) |

**Mapping:**

| `type` | Row | Fields |
|---|---|---|
| `buy` | `SecurityRow` | `instrument_identifier=isin`, `quantity=+q`, `unit_price=p`, `description=f"Buy {isin}"` |
| `sell` | `SecurityRow` | `instrument_identifier=isin`, `quantity=-q`, `unit_price=p`, `description=f"Sell {isin}"` |
| `dividend` | `CashRow` | `amount=a`, `counterparty_name=None`, `counterparty_iban=None`, `description=f"Dividend {isin}"` (or `"Dividend"` when `isin` is empty) |

**Decisions in that table, with reasons:**

- **The quantity in the file is unsigned; the sign comes from `type` only.**
  A negative quantity on a `sell` line is rejected, not negated twice into a
  buy.
- **Must-be-empty columns are enforced.** An `amount` on a buy line that the
  plugin ignored would be a reported cash movement silently discarded. The
  spec's fee Non-Goal says what the statement reports as the cash movement is
  what lands, so a format that *could* report a different one must not be
  allowed to.
- **`isin` is optional on a dividend line and is never resolved to a
  `Unit`.** A dividend is a cash row. The ISIN goes into the description so a
  rule can route it (`add-rule '^Dividend' Dividends`) through the existing
  classification path, which is all the spec asks of income rows.
- **`reference` is passed through untouched**, blank included. Whether it is
  present and unique is checked in one place, `validate_statement` (§4.3),
  not re-implemented per plugin.
- **No ISIN checksum validation.** Instrument master data is a Non-Goal, and
  the `Unit` lookup is the validation.
- **Decimals must be finite.** `Decimal("NaN")` and `Decimal("Infinity")`
  parse successfully, so the plugin checks `is_finite()`.

### 7.2 Errors

All subclass the contract's `ImportError` and carry the physical file line
number (`csv.reader.line_num`; the header is line 1):

- `UnexpectedHeader(found: list[str])`
- `UnknownRowType(line, value)` — issue 028's named parse error for an
  unknown `type`
- `MalformedField(line, column, value, problem)` — an unparseable date or
  decimal, a non-positive quantity or price, a missing required field, or a
  filled must-be-empty field
- `StatementUnreadable` from the contract, for `OSError` /
  `UnicodeDecodeError`

### 7.3 The fixture

`tests/fixtures/synthetic_broker.csv`:

```
date,reference,type,isin,quantity,price,amount
2026-03-02,T-1001,buy,DE0005190003,10,95.50,
2026-03-20,T-1002,sell,DE0005190003,4,101.25,
2026-04-15,D-2001,dividend,DE0005190003,,,12.40
```

Imported as `import-statement kohle-synthetic-broker "Broker Cash" Depot
synthetic_broker.csv`, after `add-unit DE0005190003 BMW`:

| Entry | Lines |
|---|---|
| `T-1001` | dr `Depot` 10 DE0005190003 @ 95.50; cr `Broker Cash` 955.00 EUR |
| `T-1002` | cr `Depot` 4 DE0005190003 @ 101.25; dr `Broker Cash` 405.00 EUR |
| `D-2001` | dr `Broker Cash` 12.40 EUR; cr `Unclassified Income` 12.40 EUR; one `Classification` row, `matched_rule_id NULL` |

`balance Depot` then reports 6 units at an average cost of 95.50. A second
import posts nothing and creates no `OperationGroup`.

### 7.4 Parser: stdlib `csv`, not pandas

pandas is already a dependency, but `read_csv` types `quantity` and `price`
as `float64`, and a price must never pass through a float. With `dtype=str`,
pandas becomes a heavier `csv.DictReader` that cannot report a line number.
`csv` plus `Decimal(text)` is exact, and gives `line_num` for errors.

---

## 8. Migrations: none, and the legacy-reference question

**No schema change.** `journal_entries.reference` keeps its type and its
unique constraint. No column or table is added. So there is no Alembic
revision and no downgrade to write.

**Existing hash-based references: none exist, verified.** Every `kohle.db`
on this machine was checked, read-only:

| Database | Revision | Imported entries |
|---|---|---|
| `kohle.db` (repo root; the path `alembic.ini` and `connection.py` use) | `a1cebfe54f33` | **0** — `journal_entries` is empty |
| `kohle.db.bak-20260831` | `62313518700b` (pre-multi-unit) | **0** — `transactions` is empty. `7f3c1d9a2b40_multi_unit_ledger` drops that table without carrying rows forward anyway |
| `kohle/app/plugins/kohle.db`, `kohle/app/tui/widgets/kohle.db` | — | no ledger tables (strays from running with a different cwd) |

So the scheme change from `sha256(account|date|amount|description)` to
`{account_id}:{native}` re-identifies nothing, and no data migration is
needed.

**Had there been any**, they could not be converted. A digest cannot be
inverted, and the native reference was never stored. The realistic options
would have been to refuse import into an account holding legacy-referenced
entries (they are recognisable as 64 lowercase hex characters with no `:`),
or to accept the overlap and not re-import old periods. Neither is built,
because the data says neither is reachable. **The decision rests on that
check.** `DATABASE_URL` is cwd-relative, so if the user keeps a ledger on
another machine, it should be checked before 026 lands.

`expense-classification.md` §3.6 ("the reference hash must not change") is
superseded by this design. Its reason was "previously imported rows must
still be recognised", and there are no previously imported rows.

---

## 9. All-or-nothing

The spec states this requirement "so it stays true", and the design keeps
it true without adding machinery:

- **One `ImportStatement` run is one `UnitOfWork`, which is one database
  transaction.** Every write inside it — the EUR unit, the buckets, every
  entry, every classification, and the lazily created `OperationGroup` with
  its `Operation` rows — goes through `crud_create` on the same `ctx`.
  `DbTransaction.execute` commits once at the end. Any `Err` returned from the
  closure rolls everything back, and so does any exception, at the `BLE001`
  seam.
- **The plugin runs before the transaction opens** and writes nothing. A
  plugin failure never reaches a session.
- **The rolled-back `OperationGroup` leaves no gap.** The tables use plain
  `INTEGER PRIMARY KEY` without `AUTOINCREMENT`, so SQLite reuses the
  rolled-back rowid, and group ids stay consecutive across a rejected import.
  That is the "including the audit trail" half of the spec's requirement.
- **"Byte-identical" is tested as identical table contents** — row counts
  and maximum ids in `journal_entries`, `journal_lines`, `classifications`,
  `units`, `accounts`, `operation_groups` and `operations` — not as file
  bytes, which is not a meaningful assertion for SQLite.

**The one construct that would break it** is the one the two previous
designs already named. Nothing inside `ImportStatement` may be a
`UnitOfWork`. In particular, neither branch may be pulled out into its own
use case. Both branches are `ctx`-taking code inside the one closure.

---

## 10. The decision categories

### State and data lifecycle

**The unit of success or failure is one `import-statement` invocation**: all
of its new rows post, with their classifications and audit trail, or none
do. Partial completion is not observable anywhere. Parsing has no side
effects, and posting is one transaction (§9).

- **Replayable:** yes, by design. Re-importing the same file is a no-op
  because identity is the scoped native reference (§4.4). With the dedup
  early return placed before every write (§4.2 step 5), a no-op re-import
  leaves no `OperationGroup` behind. That makes replay *invisible* in the
  audit trail, not merely harmless.
- **Reversible:** not by this feature. The ledger stays append-only. There is
  no "un-import", there never was, and the spec asks for none. A cash row is
  corrected with `reclassify`, as today. A wrongly imported trade can only be
  countered with a hand-entered `record`. `reclassify` and `split-line`
  refuse a trade entry with `NoClassificationForEntry`, because a trade has no
  classification row. Its message is reworded from "only imported lines" to
  "only imported cash lines", which stays accurate now that some imported
  lines have no classification.
- **Auditable:** every write still goes through `crud_create`, so an import's
  entries, classifications and any bucket or EUR creation appear as one group
  in `list-operations`.
- **Identity is the reference, not the content** (§4.4): a changed row under a
  reused reference is skipped.

### Error propagation

Four representations, with the seams where they change:

1. **Plugin** — plugin-specific `ImportError` subclasses, each with
   `__str__`. A plugin catches `OSError` and `UnicodeDecodeError` at its one
   file read and returns `StatementUnreadable`. **A plugin *bug* is not
   caught**, and the CLI does not wrap the plugin call in a broad `except`:
   that would add a third `BLE001` site outside the two the `AGENTS.md`
   override sanctions, and it would turn a bug into an error message that
   hides it. The spec's "failing plugin surfaces as a named error" covers
   unreadable and unparseable *input*, which the plugins name.
2. **Use case, pre-write** — `StatementError` (`MalformedStatementRow`,
   `DuplicateReferenceInStatement`, `MissingInstrumentAccount`),
   `AccountNotFoundError`, and under `UnitError` the new `UnknownInstruments`
   and `NotASecurityUnit`. The use case knows that rows came from a plugin,
   but not which plugin or which file line. That is why its errors give a row
   number (position in the returned list) and the reference, while the
   plugins' errors give file lines.
3. **Use case, posting** — `post_entry`'s `JournalError`s propagate
   unchanged: `PostingToNonLeafAccount` for a non-postable cash, instrument or
   rule-target account, and `UnbalancedEntry` (unreachable for both branches,
   since each derives both legs from one magnitude, but still checked).
   `DuplicateJournalEntry` keeps its service mapping and becomes unreachable
   from import, because the dedup filter and the within-file check together
   exclude every collision.
4. **CLI** — still never inspects an error type, and prints `str(err)`. Every
   new error defines `__str__`.

```
StatementError(Exception)
  MalformedStatementRow(row_number, field, problem)
  DuplicateReferenceInStatement(reference, first_row, second_row)
  MissingInstrumentAccount()
UnitError
  + UnknownInstruments(identifiers)
  + NotASecurityUnit(identifier, kind)

ImportStatementError = AccountNotFoundError | JournalError | UnitError
                     | StatementError | RuleError | ClassificationError
```

`DataframeValidationError` leaves the union. `DataframeMissingColumn` and
`DataframeColumnTypeMismatch` are deleted: their only producer was
`validate_df_schema`, which is deleted with the DataFrame path (the spec:
"superseded … by the types themselves").

**Unknown-instrument errors sit under `UnitError`, not `StatementError`,**
because they are unit-resolution failures and siblings of
`UnitNotFoundError`. `MissingInstrumentAccount` sits under `StatementError`
because it is detected by inspecting the statement.

### Concurrency and ownership

**Single threaded, no shared mutable state, no concurrency.** This is stated
rather than assumed, because two things here would break quietly if it
stopped being true:

- **Plugin instances must hold no state between calls** (§3.4). The CLI
  builds a fresh instance per invocation through `load_plugins`, which hides
  any violation today. A TUI holding one instance would expose it. The
  Deutsche Bank plugin already constructs its parser per call, and the
  contract docstring makes that a requirement.
- **Rows are frozen and owned by nobody after the plugin returns them.** The
  use case reads them twice and never mutates them. The `units` dict and the
  `(row, reference)` pairs are locals of one closure.

The `Session` is owned by `DbTransaction` and closed in its `finally`. The
use case borrows `ctx`. SQLite's single-writer lock is unchanged, and a
concurrent TUI import would still get "database is locked".

### Reuse

Used rather than reimplemented:

- **`post_entry` / `validate_lines`** — balance and the leaf-only rule for
  trades, with no new check. This is the fifth feature to use them as the
  extension point.
- **`existing_references_service`** — unchanged; it receives scoped
  references instead of digests.
- **`get_account_by_name_service`, `get_unit_by_identifier_service`,
  `get_or_create_unit`, `_get_or_create_account`** — unchanged.
- **`compile_rules` / `match_rule` / `add_classification_service`** — the
  whole cash branch, untouched. Broker dividends reuse it with no new
  mechanism, as the spec requires.
- **`RecordSimpleEntry`'s cross-unit line shape** — factored into
  `_cross_unit_lines` and shared (§4.6), not re-derived.
- **`Counterparty`, `LineSpec`, `UnitOfWork`, the lazy `OperationGroup`** —
  unchanged.
- **`add-unit`** — the remedy named by `UnknownInstruments`. No new command.
- **The Deutsche Bank plugin's pandas pipeline** — kept internally, with only
  its tail changed.

Introduced here and worth reusing next:

- **`CashRow` / `SecurityRow`** — the contract any future importer, bank or
  broker, emits.
- **`validate_statement`** — the one place statement shape is checked, so a
  new plugin does not re-implement reference checking.
- **`StatementUnreadable`** — the shared "couldn't read the file" error.
- **`_cross_unit_lines`** — the definition of a trade entry, which any future
  path that records a trade (a TUI form, a corporate-action importer) should
  call.

### Extension points

- **The plugin contract** is the one public seam, and the contract that
  holds it stable is the pair of row types plus the method signature. Adding
  a field *with a default* to a row type is backward-compatible. Adding a
  required field, a third row type, or changing a field's meaning is a
  contract break. As today, there is no version negotiation, so the error
  messages are the enforcement.
- **A real broker plugin replaces the synthetic one** by emitting the same
  two row types. Nothing in the use case knows the synthetic format exists.
- **Fees** (a Non-Goal) would plug in at `_cross_unit_lines`, as an extra
  line, or as a fee field on `SecurityRow`. Nothing is built for them.
  The contract does not stop a plugin emitting a fee as a separate `CashRow`;
  that would land through classification as an ordinary cash movement.
  Whether that counts as "modelling fees as separate postings" is a question
  for the real-broker spec (§13.6).
- **Non-base currency** (a Non-Goal): a `CashRow` has no currency field.
  Adding one later is a contract change. That is deliberate, recorded so it
  is not mistaken for an oversight.
- **Price fetchers** (`dev/inbox/price-fetcher-plugin.md`) must not share the
  `kohle.plugins` group as it stands: `load_plugins` raises `TypeError` for
  any entry point there that is not a `StatementImporterPlugin`. This design
  keeps that behaviour. It is recorded because it constrains the next plugin
  kind.
- **No row-type dispatch abstraction.** Two types, one `match` with
  `assert_never`. A registry or visitor would exist for a third type the spec
  says will not come.

### Build vs. buy

- **Row types — stdlib `dataclasses`.** Evaluated:
  - *pydantic* would reject a `None` price at construction, which is
    tempting. But it adds a dependency for five checks, raises
    `ValidationError` inside plugin code (a traceback, not a named import
    error), and still could not do the cross-row duplicate check, so
    `validate_statement` would exist anyway.
  - *attrs* offers nothing over `dataclass(kw_only=True)` on 3.12.
  - *`TypedDict`* has no runtime class, so `match` cannot branch on it.
  - *`NamedTuple`* is positional (the transposition hazard), and two
    different row types with equal values compare equal as tuples.
- **Synthetic CSV parsing — stdlib `csv`** over pandas (§7.4): exact
  decimals and line numbers.
- **Optional middle positional — Click's own `nargs=-1` + `metavar`**,
  verified in the venv (§5). No custom `click.Command` subclass.
- **Exhaustiveness — `typing.assert_never`** (stdlib).
- **Reference scoping — a string prefix** rather than a composite
  `(account_id, reference)` unique key. The spec keeps
  `JournalEntry.reference` as the dedup column, and the prefix needs no
  migration.
- **A native reference for the Deutsche Bank path — nothing to buy without a
  spec decision.** For option C, PyPI has `mt-940` (MT940 parsing) and
  `python-fints` (FinTS statement download). Both would need checking for
  whether the bank fills a per-entry reference before they are worth
  evaluating further (§2.4).

### Abstractions introduced

| Abstraction | Forcing problem |
|---|---|
| `CashRow`, `SecurityRow`, `StatementRow` | The spec: a security movement without a price must not be expressible, and a DataFrame (or one row type with optional instrument fields) makes it expressible. |
| `validate_statement` (pure) | A within-file duplicate reference can only be detected with the whole list in hand, and the missing-price rejection must happen before any write. As a pure function, both are testable without a database, the treatment `match_rule`, `aggregate_by_unit` and `settle` already get. |
| `_cross_unit_lines` | A hand-entered trade and an imported trade must be the same shape for the cost fold and later profit replay, and two copies are two definitions (§4.6). |
| `StatementUnreadable` | Both plugins need it, and the spec requires a named error for an unreadable file. |
| `StatementError` family, `UnknownInstruments`, `NotASecurityUnit` | Named, `__str__`-bearing errors for conditions the spec says must reject loudly. The CLI's only output is `str(err)`. |
| `SyntheticBrokerStatementImporter` | Issue 028. |

Explicitly **not** introduced, having no forcing problem:

- A common base class for the two rows. The three shared fields are
  repeated, and the union type gives `row.reference` across both.
- A helper for the scoped reference. It is computed once, in one place
  (§4.4).
- A per-plugin "reference policy" or any fallback hook. The spec forbids
  generalising one.
- A `Trade` model or table. A trade is a journal entry.
- An upfront leaf check on the named accounts. `post_entry` enforces it at
  the point of posting, and an upfront duplicate would change today's cash
  behaviour in the all-duplicates case.
- A check that the cash and instrument accounts differ. `record` does not
  check `--from` against `--to` either, and the two are the same class of
  typo.

### Alternatives rejected

| Rejected | Where | Short reason |
|---|---|---|
| Hash fallback in the use case for absent references | §2.4 E | the spec forbids generalising a fallback |
| `Customer Reference` / `Mandate Reference` as the Deutsche Bank reference | §2.2 | blank on card payments; per-mandate by definition |
| A content-derived composite key built in the use case | §2.2 | the same fallback by another name |
| Keeping a DataFrame with nullable unit and price columns | §3 | the price-less security row stays expressible, which is the spec's whole complaint |
| One row type with optional instrument fields | §3 | same |
| A third row type for dividends or interest | §4.5 | the spec: they are cash rows through the existing path |
| `Counterparty` inside `CashRow` | §3.2 | the contract would import from `services`, so every plugin would depend on the services layer |
| Default `None` on the counterparty fields | §3.1 | reintroduces the silent omission issue 013 forbade |
| A side enum instead of a signed quantity | §3.3 | two conventions in one contract; `CashRow.amount` is already signed |
| A cash amount on `SecurityRow` | §3.3 | makes unbalanced trades expressible; only fees would make it differ, and fees are a Non-Goal |
| Validating in `__post_init__` and raising | §3.3, Build vs. buy | a traceback from plugin code instead of a named error; the cross-row check needs `validate_statement` anyway |
| Scoping a trade's reference by the instrument account | §4.4 | re-import under a different instrument account double-posts the cash leg |
| Hashing the scoped reference | §4.4 | no benefit once the input is an identifier; loses readability |
| A composite `(account_id, reference)` unique key | Build vs. buy | needs a migration; the spec keeps `reference` as the dedup column |
| Stopping at the first unknown instrument | §4.7 | the user re-runs once per new holding |
| Auto-creating instrument units | §4.7 | the spec forbids it |
| `--instrument-account` as an option | §5 | deviates from the spec's positional form |
| A required fourth positional for every plugin | §5 | Deutsche Bank users would have to name an account the import never touches |
| Wrapping the plugin call in a broad `except` in the CLI | Error propagation | a third `BLE001` site, and it hides plugin bugs |
| Switching the Deutsche Bank `open()` to ISO-8859-1 | §6 | cannot be verified without a real export; risks changing ledger rows |
| pandas for the synthetic CSV | §7.4 | float prices; no line numbers |
| Ignoring stray columns in the synthetic CSV | §7.1 | silently discards a reported cash movement |
| A data migration for legacy hash references | §8 | digests cannot be inverted, and none exist |
| Splitting either branch into its own use case | §9 | commits mid-import and breaks all-or-nothing |

---

## 11. Issue mapping

| Issue | Lands |
|---|---|
| 025 typed cash rows | `CashRow` (with `reference`) and the new method signature; `StatementUnreadable`; the Deutsche Bank migration (§6) — **blocked on §2**; `ImportStatement` consumes `Sequence[StatementRow]` through the cash branch (§4.5); `_optional_str` narrowed; `validate_df_schema`, the `Dataframe*` errors and pandas leave `journal.py` and the contract; all import tests migrated to rows; README contract section |
| 026 native-reference dedup | scoped references (§4.4); `validate_statement`'s reference and duplicate checks (§4.3); `MalformedStatementRow`, `DuplicateReferenceInStatement`; the early return before any write (§4.2) |
| 027 broker trade as transfer | `SecurityRow` and the `StatementRow` union; `validate_statement`'s security checks; `_cross_unit_lines`, factored from `RecordSimpleEntry` (§4.6); the security branch; instrument resolution with `UnknownInstruments` / `NotASecurityUnit` (§4.7); `MissingInstrumentAccount`; the CLI's optional `INSTRUMENT_ACCOUNT` (§5); the `NoClassificationForEntry` wording; README |
| 028 synthetic broker plugin | the plugin, its errors and its entry point (§7); `tests/fixtures/synthetic_broker.csv`; README mention |

**Dependency order is the issue order**, and all four are gated on the §2
spec revision through 025. Within 025 the use case keeps today's content hash
for one slice: `CashRow.reference` exists, is filled by the plugin, and is
ignored until 026 switches dedup onto it. That transitional hash is computed
from typed fields, so its digests differ from today's (a `Decimal` amount
stringifies differently from a `float`). That is harmless because no stored
digests exist (§8), and 026 deletes it. Landing 025 and 026 back to back
keeps the transitional state short.

After 028 lands, `AGENTS.md`'s Context should say "statements" rather than
"bank statements", and that dedup is by native reference. That edit belongs
to the post-landing update, as it did for the People branch.

---

## 12. Testing notes

This extends the existing layers: pure functions with no fixture, use cases
against `session` / `session_factory`, the CLI through `CliRunner`.

**Write first, before touching the contract: a Deutsche Bank
characterisation test.** There is no plugin test today, so the Goal "no
change in resulting ledger rows" has nothing to hold it.

- Add `tests/fixtures/deutsche_bank_statement.csv`, hand-built from the
  plugin's grammar: account line, period, old balance, the 18-column header,
  a SEPA transfer, a `Debit Card Payment` with its timestamp in `Payment
  Details`, a credit, a row with no counterparty, and the closing balance.
- Run it through the *current* plugin and `ImportStatement`, and record
  every entry's date, description, counterparty pair, lines (account, unit,
  quantity, price, side) and classification — **everything except
  `reference`**, which this feature necessarily changes (§13.2).
- The same assertions must pass after 025. This can be written now; it does
  not touch the blocked part.

**Pure, no database:**

- `validate_statement`: an empty, whitespace or `None` reference; a duplicate
  across two cash rows; a duplicate across a cash row and a security row
  (§3.4); `unit_price=None` / `0` / `-1` / `Decimal("NaN")`; `quantity=0`; an
  empty `instrument_identifier`; and a clean mixed list returning `None`.
- `_cross_unit_lines`: a buy debits the holding and credits cash; a sell the
  reverse; the cash quantity is `q × p` at price 1. Plus a regression check
  that `RecordSimpleEntry` still produces its old lines after being moved onto
  the helper.
- The synthetic plugin against small temporary files: a wrong header; an
  unknown `type` (issue 028's criterion); a malformed decimal; a literal
  `NaN`; a negative quantity on a sell; an `amount` on a buy; a `quantity` on
  a dividend; an unreadable path. Each gives its named error with the right
  line number.

**The spec's named test — a security row without a price:**

1. `pytest.raises(TypeError)` constructing `SecurityRow` without
   `unit_price`. This is the desk-time half.
2. `ImportStatement` given `SecurityRow(..., unit_price=None)` (`# type:
   ignore[arg-type]`) as the *last* row after two valid ones returns
   `MalformedStatementRow`, and every table, `operation_groups` included, is
   unchanged. This is the "rejected before any write" half, and it also
   covers "a statement whose last row is malformed imports none of the
   preceding rows".

**Use case:**

- A buy and a sell post the lines in §4.6. The `classifications` count equals
  the *cash* row count, so security rows record nothing.
- Unknown instruments: two missing identifiers, both named in one error, and
  nothing written. A currency unit used as an instrument gives
  `NotASecurityUnit`.
- A trade with no instrument account gives `MissingInstrumentAccount`. A
  nonexistent cash or instrument account gives `AccountNotFoundError`. An
  instrument account with a child gives `PostingToNonLeafAccount`, and nothing
  is written.
- Idempotency: the second import returns `0` **and** the `OperationGroup`
  count is unchanged (§4.2 step 5).
- Scoping: the same rows imported into two cash accounts give two entries
  each. `entry.reference == f"{cash.id}:T-1001"`. Re-importing a broker file
  under a *different* instrument account posts nothing (§4.4).
- `test_counterparty_is_not_part_of_the_reference_hash` is **replaced, not
  deleted**, by: the same reference with an enriched counterparty imports
  `0`. Its intent — enrichment must not re-import — survives the change of
  mechanism.
- The `pd.NA` / `nan` cases of `test_optional_str_normalises_a_statement_cell`
  move to a Deutsche Bank plugin test, following the half of the function
  that moved.

**Fixtures.** `statement_df` / `statement_row` in `conftest.py` become a
`cash_rows` builder that numbers references by position (`"r1"`, `"r2"`, …)
unless given one explicitly. Positional references are deterministic across
two builds of the same list, so the idempotency tests keep working with no
per-test reference bookkeeping. Tests about references pass them
explicitly.

**Scenario test** (in the shape of `test_cash_envelope_scenario.py`): the
§7.3 fixture end to end. Three rows imported; `Depot` holds 6 units at an
average cost of 95.50; the dividend sits on `Broker Cash` against
`Unclassified Income`; a rule `^Dividend → Dividends` added *before* a fresh
import routes it there instead; re-import gives `0`.

**CLI.** Monkeypatch `kohle.app.cli.cli.load_plugins` to return
`{"kohle-synthetic-broker": SyntheticBrokerStatementImporter()}` and run the
four-positional form against the fixture. The three-positional form still
parses. Two instrument accounts is a usage error. A plugin error exits
non-zero with its message.

**Entry-point discovery** (issue 028's first criterion) can only be tested
against installed metadata. `importlib.metadata` reads `kohle.egg-info` /
`dist-info`, which does not see the new `pyproject.toml` entry until the
package is reinstalled (`uv sync`, or `uv pip install -e .`). The test
asserts `"kohle-synthetic-broker" in load_plugins()`. It fails on a stale
install, and that failure means "reinstall", not "bug".

---

## 13. What the spec and the issues got wrong

Recorded because the design deviates from them, and a later reader needs to
know it was deliberate.

1. **The Deutsche Bank statement has no native per-row reference** (§2). The
   spec's Overview says the first *broker* format carries one, which is true,
   but its Goals also make the Deutsche Bank plugin pass against a contract
   that requires one, and its Non-Goals forbid the only key that format can
   supply. These cannot all hold. **Blocking; needs a spec revision.**
2. **"The existing Deutsche Bank plugin and its import tests pass … with no
   change in resulting ledger rows"** — there are no Deutsche Bank plugin
   tests, and the import tests feed hand-built DataFrames that have to be
   migrated to rows anyway. Also, `journal_entries.reference` is a ledger
   column that this feature necessarily changes. The design reads the Goal
   as "same entries, lines, counterparties and classifications, `reference`
   excepted", and adds the characterisation test that makes that checkable
   (§12).
3. **Issue 028's "the dividend lands as a cash credit on the CLI-named cash
   account"** uses bank-statement language. Money credited to a bank account
   is a **debit** on the asset account in the ledger (`is_debit=True`), with
   the credit on `Unclassified Income`. A test asserting `is_debit=False` on
   the cash line would be wrong.
4. **The spec's hint `add-unit <identifier> <name> security`** is not the
   real syntax. The command is `add-unit IDENTIFIER NAME [--kind KIND]`, and
   the kind defaults to `security`. `UnknownInstruments` prints the real
   form.
5. **"Unbalanced entry" in the spec's rejection list is unreachable for
   imported rows.** Both branches derive both legs from one magnitude.
   `post_entry` still checks, so the claim holds; it just has no test that
   can trigger it from an import.
6. **"Whatever the statement reports as the cash movement is what lands"**
   (fee Non-Goal) holds for the synthetic format only because buy and sell
   rows carry no cash amount, so the cash movement *is* `quantity × price`.
   A real broker statement reports cash that includes fees, and possibly
   sub-cent rounding on fractional shares. Under this contract it would land
   as `quantity × price`, or the plugin would have to fold the fee into the
   price. The real-broker spec has to choose; v1 does not.
7. **Issue 025's "an unreadable or unparseable file surfaces as a named
   error" is not true today.** The Deutsche Bank plugin's errors print empty
   messages, and a decode failure raises out of `open()` (§3.4, §6). 025
   fixes both.
8. **The spec places the cash branch at `journal.py:328-345,391-393` and
   calls it "unchanged".** Its *behaviour* is unchanged. Its code moves in
   three mechanical ways (§4.5), the dedup early return moves before the
   bucket get-or-create (§4.2), and the `pd.isna` half of `_optional_str`
   moves to the plugin. None of this changes a ledger row.
9. **Issue 028 leaves the description of broker rows, and whether a
   dividend line carries an ISIN, undefined.** Both are settled in §7.1, in
   the way that lets a dividend rule match through the existing
   classification path.
10. **The spec's CLI form makes the instrument account mandatory.** The
    design keeps it positional but optional (§5), so cash-only statements
    keep the three-argument form they have today.

**Incidental, out of scope:** `plugin_manager.load_plugins` raises
`ValueError("fDuplicate plugin name: {instance.name}")`. The `f` is inside
the string, so the plugin name is never interpolated. With a second plugin
now shipping, that path is marginally more reachable. It is a one-character
fix for a `change`, not this feature.
