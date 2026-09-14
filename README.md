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

### Reading the ledger

```bash
kohle-cli balance Broker                              # holdings per unit
kohle-cli entries-in-period Groceries 2026-03-01 2026-04-01
kohle-cli list-operations                             # the audit trail
```

`balance` reports one row per unit with its average cost, and rolls up across
an account's whole subtree. There is no market valuation: without a price
feed the only value information available is what was paid.

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
    def import_statement(self, statement_path: str) -> Result[pd.DataFrame, ImportError]:
        pass
```

The returned frame carries five columns and describes cash movements only:

| column              | dtype    | meaning                                |
|---------------------|----------|----------------------------------------|
| `description`       | string   | free text from the statement           |
| `amount`            | float    | signed; negative is money leaving      |
| `date`              | datetime | booking or value date, plugin's choice |
| `counterparty_name` | string   | who the other side was                 |
| `counterparty_iban` | string   | the other side's IBAN                  |

`counterparty_iban` is the *other* side's IBAN, not the imported account's.

A format that carries no counterparty at all still declares the column, empty
(`df.assign(counterparty_iban=pd.Series(pd.NA, index=df.index, dtype="string"))`).
Missing it is a hard failure naming the column, because a counterparty that
silently goes missing is what makes a classification rule stop matching with
nothing saying why. Cast the text columns with `.astype("string")`: `read_csv`
types a column that is empty on every row as `float64`, which the schema check
rejects.

Importing a broker statement needs unit and price on each row, which this
contract cannot yet express — see
`dev/inbox/importer-plugins-for-assets.md`.
