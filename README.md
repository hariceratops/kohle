# kohle
A command line money manager  
Kohle ist umgangssprachlich für 'Geld' im Deutschen

> [!WARNING]
> The app is highly personalized

Kohle keeps a multi-unit, double-entry ledger. Every account is an account —
bank accounts, virtual sub-accounts for earmarked savings, instruments,
expense categories — and every journal line carries a quantity, the unit it is
denominated in, and the price that unit had at the time of the transaction.
Cash in the base currency is stored at price 1, so cash lines and asset lines
have the same shape.

A parent account's balance is the sum of its children, so only leaf accounts
may be posted to.

### Running
To run the app, install the application into a uv venv, activate the venv and run the application
```bash
uv init
uv sync
source .venv/bin/activate
kohle-cli
```

### Where the ledger lives
Every entry point (`kohle-cli`, `kohle-tui`, and the `alembic` command) finds
the ledger the same way, whatever the working directory:

1. `KOHLE_DB`, if set and non-empty;
2. else `$XDG_DATA_HOME/kohle/kohle.db`;
3. else `~/.local/share/kohle/kohle.db`.

There is no `--db` flag; `KOHLE_DB` is the only selector.

A ledger from before this change sits at `./kohle.db`. Move it once, by hand:
```bash
mkdir -p ~/.local/share/kohle && mv ./kohle.db ~/.local/share/kohle/kohle.db
```

### Writing migrations
The Alembic migrations ship inside the package, in `kohle/db/migrations/`.
From the repo root:
```bash
alembic revision --autogenerate -m "..."
```
This compares the models with the ledger at the resolved location (or
`KOHLE_DB`). `alembic upgrade` is a developer tool.

> [!NOTE]
> `kohle-tui` is currently unwired and does not start. See
> `dev/inbox/tui-wiring.md`.

To run the tests, install dev dependencies and run tests from the root folder
```bash
uv sync --extra dev
uv run pytest tests/
```

`--extra dev` is not optional for the test run: a bare `uv sync` prunes the
dev dependencies and `pytest` disappears from the venv.

### Accounts and units

```bash
kohle-cli add-account Checking --type asset --iban DE00...
kohle-cli add-account Cash --type asset
kohle-cli add-account Groceries --type asset --parent Cash   # a virtual envelope
kohle-cli add-unit IE00B4L5Y983 "Core MSCI World" --kind security

kohle-cli list-accounts            # the whole tree
kohle-cli list-accounts Cash       # one subtree
kohle-cli list-units
```

`list-accounts` renders the hierarchy, marking parents with a trailing `/`:

```
account         type     iban
--------------  -------  ------
Cash/           asset    -
|- Groceries    asset    -
|- Unallocated  asset    -
Checking        asset    DE00...
```

Only the unmarked accounts can be posted to.

### Recording entries

The two-line case — an expense, a transfer, an envelope allocation:

```bash
kohle-cli record 2026-03-05 "Aldi" 80 --from Checking --to Groceries
```

`--from` is credited, `--to` is debited. Buying or selling a non-base unit
names the side that carries it:

```bash
kohle-cli record 2026-03-06 "Buy ETF" 10 \
    --from Checking --to Broker --to-unit IE00B4L5Y983 --to-price 100

kohle-cli record 2026-03-07 "Sell ETF" 10 \
    --from Broker --to Checking --from-unit IE00B4L5Y983 --from-price 110
```

Anything with more than two lines gives every line in full, as
`ACCOUNT:QUANTITY:UNIT:PRICE:SIDE`:

```bash
kohle-cli record-split 2026-03-05 "Shared dinner" \
    --line Checking:120:EUR:1:credit \
    --line Alice:60:EUR:1:debit \
    --line Bob:60:EUR:1:debit
```

Entries must balance by value, not by quantity — which is what lets 10 shares
at 100 balance 1000 EUR.

To move shares between two of your own depots, credit one and debit the other
in the same entry. `realised` treats this as a move, not a sale: the lots keep
their original dates and costs, and any equal price balances the entry.

```bash
kohle-cli record-split 2026-05-01 "Move to DepotB" \
    --line DepotA:10:IE00B4L5Y983:100:credit \
    --line DepotB:10:IE00B4L5Y983:100:debit
```

An entry that moves a different quantity out than in fails `realised` with
`UnbalancedOwnMove`; record a sale or purchase as its own entry.

### Reading the ledger

```bash
kohle-cli balance Broker                              # holdings per unit
kohle-cli entries-in-period Groceries 2026-03-01 2026-04-01
kohle-cli list-operations                             # the audit trail
```

`balance` reports one row per unit and rolls up across an account's whole
subtree. Each row shows what was paid (`average cost`) beside the latest stored
close and the market value it gives, with the same `status` words as
[`net-worth`](#net-worth) and the same `--max-age-days N` flag:

```
unit            quantity    price  price date      market value  status                average cost
------------  ----------  -------  ------------  --------------  ------------------  --------------
EUR               250.00     -     -                     250.00  -                             1.00
IE00B4L5Y983       10.00   112.40  2026-10-09           1124.00  fresh                       100.00
DE0005190003        3.00    80.50  2026-09-01            241.50  stale (2026-09-01)           75.00
XAU-G             100.00     -     -                    5500.00  no price (at cost)           55.00

Market value: 7115.50
2 of 3 holdings estimated (1 stale, 1 at cost)
```

`Market value` is the sum of the unit rows, and the last line counts estimated
holdings as in `net-worth`. Both lines print only when the account holds at
least one non-euro unit with a nonzero quantity; a euro-only account (or one
whose other units are sold out) shows the columns alone, and its
`Total (base currency)` row repeats the quantity as its market value. Reports
read stored closes and never fetch (see [Prices](#prices)).

`entries-in-period` shows the counterparty an imported line came from, or `-`
for entries made by hand, which have none.

A failing command exits non-zero and writes to stderr, so `kohle-cli ... ||
handle-failure` works and a redirect captures results rather than errors.

### Classification rules

An imported line that matches no rule lands in `Unclassified Expense` or
`Unclassified Income`. A rule sends it somewhere better:

```bash
kohle-cli add-rule 'REWE|ALDI|LIDL' Groceries
kohle-cli add-rule '^DE89370400440532013000$' Rent --priority 10
kohle-cli list-rules
kohle-cli remove-rule 3
```

The pattern is a Python regular expression, matched case-insensitively against
the description, the counterparty name and the counterparty IBAN, each on its
own — which is what makes `^DE89...$` mean "this exact counterparty IBAN".
`(?-i:REWE)` restores case sensitivity inside a pattern. A malformed pattern is
refused when the rule is created, naming the position:

```
$ kohle-cli add-rule 'REWE[' Groceries
Error: Invalid rule pattern 'REWE[': unterminated character set at position 4
```

Rules are evaluated lowest `priority` first, ties broken by id, and the first
match wins — which is the order `list-rules` prints them in. `--priority`
defaults to 100, leaving room to slot a rule either side of an existing one
without renumbering.

The target must be a leaf account, since only leaves can be posted to.
`remove-rule` retires a rule rather than erasing it: past classifications keep
naming the pattern that made them.

Rules are applied while a statement is imported: each row takes the account its
first matching rule names, and a row matching nothing lands in its unclassified
bucket exactly as it did before any rule existed. If a rule's target has since
gained a child account the import fails naming it, rather than quietly falling
back to the bucket and leaving the rule silently disabled.

Every imported row is recorded either way — what was proposed, which rule
matched (none, for a fall-through), where it landed, and whether a human has
corrected it. That record is what a later classifier would learn from, which is
why it is written from the first line classified rather than added afterwards.

```bash
kohle-cli list-unclassified
```

Lists every imported line still sitting in `Unclassified Expense` or
`Unclassified Income` — the queue of lines that need a new rule or a manual
correction. Each row carries enough to write a rule from it: the entry id,
date, description, counterparty, amount and the account it landed on. Nothing
imported yet, or everything already classified, both print `No unclassified
lines` rather than an error; the command is read-only and creates no accounts
and no operation group of its own.

```bash
kohle-cli reclassify 42 Groceries
```

Moves a classified line onto a different account — whether it was matched by a
wrong rule or fell through to an unclassified bucket — by posting a reversing
pair through `post_entry`: the wrong account is credited and the right one
debited, for the original amount, dated the same day as the original entry.
The original entry is never edited, voided or deleted; the ledger stays
append-only. `42` is the journal entry id, exactly what `list-unclassified`
prints in its first column.

The classification record moves with it: `final_account_id` becomes the new
account and `corrected` is set, while the proposed account and the rule that
matched are left exactly as they were — they are the record of what the
engine got wrong, not something a correction should erase. Reclassifying an
already-corrected line reverses out of its current account, not its original
proposal, so a second correction lands the amount on the new target without
disturbing the first.

An unknown entry id, an unknown target account, or a non-leaf target all fail
with a clear error rather than a traceback.

### Splitting an imported line with someone else

People are ordinary accounts, created under the seeded `People` root with
the account command every other account uses:

```bash
kohle-cli add-account Alice --type asset --parent People
```

An already-imported line can then be divided between your own share and one
or more people, after the fact:

```bash
kohle-cli split-line 42 --mine 32 --share Alice:48
```

`42` is the journal entry id, printed by `entries-in-period`'s first column.
`--mine` is required and states your own share; every `--share PERSON:AMOUNT`
adds a person's share, repeatable for more than one person. The three must
sum to the original line's amount exactly — `--mine 32 --share Alice:40` on
an 80 EUR line fails naming both figures, rather than silently posting a
line that no longer balances against what was imported.

The split posts a reversing-and-re-posting adjusting entry through the same
mechanism `reclassify` uses: the original line is never edited, voided or
deleted. An €80 dinner split `--mine 32 --share Alice:48` leaves the expense
account holding 32 and `Alice` holding a 48 receivable. Splitting a line that
was reclassified first takes the shares out of the corrected account, not
the original bucket; splitting first and then reclassifying is refused,
since the account reclassify would reverse out of no longer holds the full
amount.

Only imported lines can be split — a hand-entered `record`/`record-split`
line has no classification to split against, and fails the same way
`reclassify` does on one. An unknown entry id, an unknown or non-`People`
target account, and shares that don't sum to the line's amount all fail with
a clear error rather than a traceback.

### Undoing or editing a split

A split can be undone entirely:

```bash
kohle-cli unsplit-line 42
```

`unsplit-line` posts a mirror of the split's current adjusting entry — same
accounts, units, quantities and prices, every side flipped — which restores
the expense account and person account balances to exactly what they were
before the split, with no arithmetic of its own. The original entry and the
first split's adjusting entry are both left exactly as they were; the undo is
a further entry, not an edit. An unknown entry id, or one with no current
split to undo, fails with a clear error rather than a traceback.

A split can also be corrected to different shares by re-running `split-line`
on the same entry:

```bash
kohle-cli split-line 42 --mine 40 --share Alice:40
```

Re-splitting an already-split entry replaces the allocation rather than
refusing: it mirrors the existing adjusting entry (exactly what
`unsplit-line` posts) and then posts the new split, both in one transaction,
so a failure anywhere leaves the previous split intact. Nothing needs to be
undone first. The full history — the original import, the first split, and
the correction pair — stays readable through `entries-in-period` and
`list-operations`; only the `splits` row's current pointer moves.

### Grouping splits under a trip label

A split can optionally be tagged with a group — a trip label that ties
several splits together. Groups are created explicitly and looked up
strictly, the same rule that stops a typo in `--from` from becoming a new
account:

```bash
kohle-cli add-group "Italy trip"
kohle-cli split-line 42 --mine 32 --share Alice:48 --group "Italy trip"
```

`--group` is authoritative on every run of `split-line`: omitting it clears
the split's group, and naming a different one moves it. Splitting a line
without `--group` works exactly as before — grouping is additive. An unknown
group name fails with a clear error rather than silently creating a second
group with a similar spelling.

### Reporting who owes what

`who-owes-what` lists the net balance of every account under `People` — the
same figure `balance Alice` would give, for everyone at once:

```bash
kohle-cli who-owes-what
```

Every person account is listed, including one that has never been split
against — it renders as `-`, distinct from a settled person's `0.00`, whose
lines exist and happen to cancel out.

```bash
kohle-cli who-owes-what --by-group
```

`--by-group` breaks the view down into one block per group, including a group
with no splits yet, so this doubles as the group listing. Splits with no
group appear in neither block, and the global view is unaffected either way.
The per-group column is labelled `from splits`, not `balance`: it sums the
current adjusting entries in that group only, so it is a historical
allocation — what a trip cost each person — not a live, settlement-adjusted
balance. If Alice has since paid you back, `who-owes-what` shows it and the
group total still doesn't, which is why the two are never labelled the same
thing.

### Suggesting settling transfers

`settle-up` suggests the minimum set of transfers that zeroes out every
current person balance — three people who cancel through one intermediary
need one transfer, not three:

```bash
kohle-cli settle-up
```

```
payer   payee   unit   quantity
------  ------  -----  --------
Alice   Bob     EUR       50.00

Settle with: kohle-cli record <date> "<description>" 50.00 --from Alice --to Bob
```

`you` stands in for your own side of a transfer. The command has no way to
know which of your accounts should stand in for "you" in a `record`
invocation — a "default cash account" setting would be a configuration
mechanism this codebase does not have — so `<your account>` is left for you
to fill in, along with the date and description.

```bash
kohle-cli settle-up --group "Italy trip"
```

`--group` restricts the suggestion to a group's participants while keeping
each of their full, current balances — not the group's historical
allocation total — and recomputes your own position as the negation of just
that subset. Netting runs once per unit: euros and shares are never combined
into one suggestion. Nothing is written; this is a pure read over current
balances, computed fresh on every call, and `No transfers needed` prints when
every balance is already zero.

### Net worth

`net-worth` totals your own accounts plus what's owed to you (the `People`
branch, per-person balances are `balance <person>` or `who-owes-what`):

```bash
kohle-cli net-worth
```

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

The total folds receivables in rather than reporting them next to net worth,
but the breakdown above is what makes that checkable instead of a bare number
you have to trust. Income and expense accounts are excluded — every entry
balances, so including them would always report exactly 0. A person account
with a negative balance (you owe them) lowers the total; a positive one
(they owe you) raises it.

Each holding is shown twice: **at cost** (what you recorded, the moving
average) and **at market** (quantity times the latest stored close). The close
comes from the `prices` table that `fetch-prices` fills; reports never fetch.
The `status` column says where a market value came from:

- `fresh`: the latest close is at most 7 days old (`--max-age-days N` changes
  the 7; `0` means only today's close is fresh).
- `stale (YYYY-MM-DD)`: the latest close is older; it is still used, and its
  date is shown.
- `no price (at cost)`: no close is stored (never fetched, no price source
  bound, or a unit that has no price), so the holding is valued at cost.
- `-`: euros are worth their quantity, and a holding with quantity 0 is worth
  0; neither looks up a close.

`Net worth (at cost)` is unchanged and `Net worth (at market)` is the sum of
every row's market value in both sections. Receivables stay at face value.

The last line counts the holdings whose market value is an estimate: rows
other than euros with a nonzero quantity (3 above), of which those with a
`stale` or `no price (at cost)` status are estimated. It always prints, as
`0 of M holdings estimated` when none are.

### Positions and profit

`realised` replays each depot's buys and sells in ledger order and lists every
sale with its gain computed against the **oldest lots first** (FIFO, per
depot):

```bash
kohle-cli realised
kohle-cli realised --year 2026
```

```
date        account    unit            quantity    proceeds    FIFO cost    gain
----------  ---------  ------------  ----------  ----------  -----------  ------
2026-03-10  Depot      IE00B4L5Y983       15.00     1950.00      1600.00  350.00

Realised gain: 350.00
```

Proceeds are the quantity sold times the sale line's recorded unit price. The
figures are gross, before fees and tax, so they serve as a cross-check against
your broker's certificate, not as a tax computation. `--year` lists only sales
dated in that year; their gains still use lots bought in earlier years.
Without it every sale from all years is listed under one total. The `People`
branch is excluded. `No sales` prints in place of the table when there are
none; `Realised gain: 0.00` still closes the output.

`positions` lists each security still held, summed across all own accounts
(the `People` branch is excluded), at its latest stored close beside the FIFO
cost of the lots still held:

```bash
kohle-cli positions
kohle-cli positions --max-age-days 14
```

```
unit            quantity    price  price date      market value  status                FIFO cost    unrealised gain
------------  ----------  -------  ------------  --------------  ------------------  -----------  -----------------
IE00B4L5Y983        5.00   112.40  2026-10-09            562.00  fresh                    600.00             -38.00
DE000A0F5UF5        4.00     -     -                     200.00  no price (at cost)       200.00               0.00

Market value: 762.00
FIFO cost: 800.00
Unrealised gain: -38.00
1 of 2 holdings estimated (0 stale, 1 at cost)
```

`unrealised gain` is `market value` minus `FIFO cost`. The status words and
the `K of M holdings estimated` line are `net-worth`'s, and `--max-age-days`
(default 7) behaves the same. A security with no stored close is valued at its
FIFO cost, so its gain is 0 and the row is marked `no price (at cost)`.
`No positions` prints in place of the table when nothing is held. `positions`
never fetches prices.

`positions` and `realised` fail, printing nothing else, when the ledger is
inconsistent: a sale exceeding the lots its depot holds (the error names the
unit, account, date and shortfall), or a security moving between an own
account and a `People` account (the error names the entry).

Note that `balance`'s `average cost` is a moving average, while `positions`
and `realised` use FIFO, so they can disagree about what a lot cost.

### Net worth over time

`net-worth-history` shows net worth at past sample dates: the 15th and the salary
day (the last working day) of each month, plus a final row dated `--to` when that is not
itself a sample date:

```bash
kohle-cli net-worth-history
kohle-cli net-worth-history --from 2026-01-01 --to 2026-10-12
```

```
date          at cost    at market  estimated
----------  ---------  -----------  -----------
2026-08-15   10210.00     10294.50  1 of 3
2026-08-31   12890.00     12961.20  1 of 3
2026-09-15   12650.00     12702.00  2 of 3
2026-09-30   15330.00     15391.10  1 of 3
2026-10-12   15105.00     15188.40  1 of 3
```

Each row values the ledger as `net-worth` does, using only the lines dated on or
before that date (a line dated on a sample date is included, the next day's is
not). Every non-euro holding is valued at its last stored close on or before
that date, never a later one. A close within `--max-age-days` (default 7) of the
row's date is fresh, an older one is stale, and a date before any close is
valued at cost; both of the latter count in `estimated`, which reads `K of M`
as in `net-worth`'s last line.

`--period-end last-working-day` (the default) samples each month's second date
on its last working day: Monday to Friday, not a public holiday of the
`--state` Bundesland (default `BY`, a two-letter code such as `BE` or `NW`), and
never 24 or 31 December. A month ending on a Saturday or a holiday therefore
samples the working day before it, and December is 30 December when that is a
weekday (2028: Friday 29 December). The 15th never moves. The row is dated that
day and includes its lines. `--period-end month-end` keeps the calendar last
day, and then `--state` has no effect. An unknown `--state` is a usage error.
Holidays come from the pinned `holidays` package, so a deliberate upgrade of it
can move a date.

`--from` defaults to the earliest ledger entry and `--to` to today. A `--to`
after today, or a `--from` later than `--to`, is a usage error. With `--to`
omitted the last row equals what `net-worth` prints today, unless an entry is
dated in the future, which `net-worth` counts and the history does not. The
report never fetches prices.

### Prices
Current prices come from price plugins, a second plugin kind in the same
`kohle.plugins` entry-point group as the importers. Fetching is always an
explicit command; recording, importing and reports never fetch, and recorded
entries never depend on a price.

```
kohle-cli set-price-source IE00B4L5Y983 alphavantage VWCE.DEX
kohle-cli set-price-source DE0005190003 file BMW
kohle-cli fetch-prices
```

`set-price-source UNIT PLUGIN SYMBOL` binds a `security` unit to exactly one
plugin and the symbol that plugin knows it by; running it again replaces the
binding. The symbol is never guessed. Binding a symbol is also your assertion
that it quotes in EUR: only EUR closes are accepted, and a wrongly bound
foreign-currency symbol cannot be caught.

`fetch-prices` asks each plugin once for the latest daily close of the
securities you hold that are bound to it, and appends it to the price history.
It prints one row per held security: `priced` (with the previous stored close),
`already stored`, `unpriced` with a reason, or `unbound`. It exits non-zero if
any bound unit ends unpriced; an unbound unit alone is not an error. There is
no fallback to another plugin: to change a unit's source, rebind it. History is
append-only and a date is stored once, so re-running is a no-op, and a wrong
stored close cannot be corrected in this version.

Every close is checked before it is written: the price must be finite and above
zero, the date not in the future, the currency EUR. A rejected close leaves only
that symbol's units unpriced.

#### Bundled price plugins
- `file`: reads `identifier,date,close` rows from the CSV named by the
  environment variable `KOHLE_PRICE_FILE` and returns each symbol's most recent
  row. It works offline, and is the way to price a unit no other plugin covers.
- `alphavantage`: Alpha Vantage `TIME_SERIES_DAILY`, with the API key in
  `KOHLE_ALPHAVANTAGE_KEY`. It stores the latest daily bar dated before today
  (UTC), so a trading day still in progress is never stored. The free tier
  allows one symbol per request and about 25 requests a day; symbols are
  requested oldest stored close first so prices rotate, and a throttled run
  keeps what it fetched and reports the rest as `transient`. Symbols carry the
  exchange suffix (for example `.DEX`), so look up the EUR listing yourself.

Physical gold and other commodity units are not priced yet.

#### Writing price plugins
Subclass `PriceFetcherPlugin` from `kohle.plugin.price_plugin` and register it
under `kohle.plugins` as for importers. The one method takes the requested
symbols and returns, per symbol, a `Close` (date, `Decimal` price, currency) or
`Unavailable` (`no_symbol`, `not_covered` or `transient`); a failure of the
whole plugin, such as being offline or a missing key, is an error value. A
plugin must not do I/O or read configuration when constructed, and must spend
requests in the order given. Nothing in core needs to change.

### Writing importer plugins
A new plugin can be rolled out by defining an entry point to kohle plugins
```toml

[project]
name = "kohle-hello-plugin"
version = "0.1.0"
description = "Hello world plugin for Kohle"

dependencies = ["kohle"]

[project.entry-points."kohle.plugins"]
hello_world = "kohle_hello_plugin.plugin:HelloWorldPlugin"
```

A importer plugin shalll satisfy the contract of base class StatementImporterPlugin defined in kohle.plugin.importer_plugin
```python
class StatementImporterPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def import_statement(self, statement_path: str) -> Result[list[StatementRow], ImportError]:
        pass
```

`import_statement` returns one row per statement line, in order: a `CashRow` for
a cash movement, a `SecurityRow` for a trade. All fields are required keyword
arguments. A `CashRow` has:

| field               | type          | meaning                                           |
|---------------------|---------------|---------------------------------------------------|
| `entry_date`        | `date`        | booking or value date, plugin's choice            |
| `reference`         | `str`         | unique per row; dedup key, scoped to the account  |
| `description`       | `str`         | free text from the statement                      |
| `amount`            | `Decimal`     | signed; negative is money leaving                 |
| `counterparty_name` | `str \| None` | who the other side was                            |
| `counterparty_iban` | `str \| None` | the other side's IBAN                             |

`counterparty_iban` is the *other* side's IBAN, not the imported account's. A
format with no counterparty data passes `None` explicitly, so omitting it is
a `TypeError` rather than a silent gap.

A `SecurityRow` has `entry_date`, `reference` and `description` as above, plus:

| field                   | type      | meaning                                           |
|-------------------------|-----------|---------------------------------------------------|
| `instrument_identifier` | `str`     | the `Unit.identifier` of a `security` unit        |
| `quantity`              | `Decimal` | signed; positive is a buy, negative a sell        |
| `unit_price`            | `Decimal` | base currency per unit, finite and above zero     |

There is no cash amount on a trade: the cash leg is `abs(quantity) *
unit_price`. A trade posts one balanced entry between the cash account and the
instrument account (a buy debits the instrument and credits cash; a sell the
reverse), runs no classification rules and records no classification, so it
cannot be reclassified or split. A row with a missing, zero, negative or NaN
price, a zero quantity or an empty identifier rejects the whole import before
anything is written.

`reference` is the statement's own per-row id. A format that has none (the
Deutsche Bank CSV) derives it from row content inside the plugin.

An unreadable or unparseable file is returned as an `ImportError` subclass
whose `__str__` says what is wrong (`StatementUnreadable` covers I/O and
decoding); nothing is written. A plugin holds no state between calls.

Statements are imported with:

```
kohle-cli import-statement PLUGIN CASH_ACCOUNT [INSTRUMENT_ACCOUNT] STATEMENT_FILE
```

`INSTRUMENT_ACCOUNT` is required when the statement contains trades and
optional otherwise. Every instrument identifier must already exist as a
`security` unit (`kohle-cli add-unit <identifier> <name>`); unknown ones are
all named in a single error and nothing is imported. A reference is scoped to
the cash account, so re-importing a file posts nothing.

#### Bundled plugins
- `kohle-deutsche-bank`: Deutsche Bank CSV, cash rows only.
- `kohle-simple-broker`: a simple broker CSV that exercises the contract
  until a real broker format is chosen. UTF-8, header exactly
  `date,reference,type,isin,quantity,price,amount`. `type` is `buy`, `sell` or
  `dividend`. Buys and sells (`isin`, unsigned `quantity > 0`, `price > 0`, no
  `amount`) become `SecurityRow`s; a dividend (`amount` in EUR, `isin`
  optional, no quantity or price) becomes a `CashRow` described `Dividend
  <isin>`, so a rule such as `add-rule '^Dividend' Dividends` routes it.
  Parse errors name the file line; an unknown `type` or a filled column that
  must be empty writes nothing.

```
kohle-cli add-unit DE0005190003 BMW
kohle-cli import-statement kohle-simple-broker "Broker Cash" Depot statement.csv
```
