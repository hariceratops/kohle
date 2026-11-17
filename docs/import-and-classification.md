# Import and classification

Importing bank statements and classifying them with rules.

A statement is imported into a cash account with the importer plugin that
reads its format. The sample below is a fictional Deutsche Bank export,
`statement.csv`, shipped with these docs.

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeeded, 9 entries imported
```

`import-statement` takes the importer plugin, the cash account the statement
belongs to and the file. `list-importer-plugins` names the importers that are
installed, and [Plugins](plugins.md) says what each accepts:

```console
$ kohle-cli list-importer-plugins
kohle-deutsche-bank
kohle-simple-broker
```

Each statement row becomes one entry on the cash account, and its other side is
decided by the classification rules below. The date is the booking date,
except that a card payment takes the date printed in its payment details, which
is why the 7 April purchase is dated 6 April.

## The unclassified buckets

Before any rule exists, every row falls through. Money spent lands in
`Unclassified Expense` and money received in `Unclassified Income`, both
created on the first import. `list-unclassified` lists what is still in them,
which is the queue of lines that need a rule or a manual correction:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeeded, 9 entries imported
$ kohle-cli list-unclassified
  entry_id  date        description                                         counterparty              amount  account
----------  ----------  --------------------------------------------------  ----------------------  --------  --------------------
         1  2026-04-01  Rent April                                          Erika Beispiel            900.00  Unclassified Expense
         2  2026-04-06  Card 0001 FRISCHMARKT 06-04-2026T17:20:41 purchase  FRISCHMARKT                38.60  Unclassified Expense
         3  2026-04-14  Card 0001 KORNLADEN 14-04-2026T10:05:09 purchase    KORNLADEN                  21.45  Unclassified Expense
         4  2026-04-20  Dinner shared with Jonas                            Trattoria Roma             64.00  Unclassified Expense
         5  2026-04-28  Salary April                                        Beispiel Software GmbH   2600.00  Unclassified Income
         6  2026-05-01  Rent May                                            Erika Beispiel            900.00  Unclassified Expense
         7  2026-05-08  Card 0001 FRISCHMARKT 08-05-2026T16:48:33 purchase  FRISCHMARKT                45.20  Unclassified Expense
         8  2026-05-21  Card 0001 KORNLADEN 21-05-2026T11:12:50 purchase    KORNLADEN                  19.80  Unclassified Expense
         9  2026-05-28  Salary May                                          Beispiel Software GmbH   2600.00  Unclassified Income
```

Each row carries enough to write a rule from it: the entry id, date,
description, counterparty, amount and the account it landed on. The entry id is
the handle the other commands take. With nothing imported yet, or everything
classified, it prints `No unclassified lines` instead of an error. It only
reads: it creates no account and no entry of its own.

Every imported row is recorded either way: what was proposed, which rule
matched (none, for a fall-through), where it landed and whether a human has
corrected it.

## Rules

A rule is a set of conditions and a target account. The rules are an ordered
list, and the first rule whose conditions all hold decides where a row goes. A
row that matches none lands in its unclassified bucket. The target must be a
leaf account, because only leaves can be posted to.

Rules are kept in one file that is read and replaced as a whole. The simplest
rule tests one regular expression over the description, the counterparty name
and the IBAN with `any_field`. Here is a rule file for the sample statement,
written to `rules.toml`:

<!-- docs: file rules.toml -->
```toml
[[rule]]
account = "Rent"
note = "landlord"
[rule.when]
iban = "DE02120300000000202051"
amount = { min = 400, max = 1500 }
direction = "out"

[[rule]]
account = "Groceries"
[rule.when]
any_field = "FRISCHMARKT|KORNLADEN"

[[rule]]
account = "Salary"
[rule.when]
counterparty = "Beispiel Software"
direction = "in"
```

`apply-rules FILE` replaces the stored rules with the file's. It prints a
summary of what changes and asks `Apply these changes?`; `--yes` skips the
question. The target accounts must exist first:

<!-- docs: uses rules.toml -->
```console
$ kohle-cli add-account Rent --type expense
Added account Rent (expense) with id 2
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 3
$ kohle-cli add-account Salary --type income
Added account Salary (income) with id 4
$ kohle-cli apply-rules rules.toml --yes
3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
  rule 1 (new) -> Rent { iban = "DE02120300000000202051", amount = { min = 400, max = 1500 }, direction = "out" }
  rule 2 (new) -> Groceries { any_field = "FRISCHMARKT|KORNLADEN" }
  rule 3 (new) -> Salary { counterparty = "Beispiel Software", direction = "in" }
Applied: 3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
```

A target that does not exist, or that has sub-accounts, is refused when the
file is applied, naming the rule and the key, and so is a malformed pattern.
Nothing is changed:

<!-- docs: file leaf.toml -->
```toml
[[rule]]
account = "Food"
[rule.when]
description = "BAKERY"
```

<!-- docs: uses leaf.toml -->
```console
$ kohle-cli add-account Food --type expense
Added account Food (expense) with id 2
$ kohle-cli add-account Bakery --type expense --parent Food
Added account Bakery (expense) with id 3
$ kohle-cli apply-rules leaf.toml --yes
Error: rule 1, account: 'Food' has sub-accounts; a rule must send lines to a leaf account
```

Rules apply as a statement is imported: each row takes the account its first
matching rule names, and a row that matches nothing lands in its unclassified
bucket as it would with no rules at all. With the rules above in place the
sample imports almost completely classified, and only the shared dinner is left
for you:

<!-- docs: uses rules.toml -->
```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Rent --type expense
Added account Rent (expense) with id 3
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 4
$ kohle-cli add-account Salary --type income
Added account Salary (income) with id 5
$ kohle-cli apply-rules rules.toml --yes
3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
  rule 1 (new) -> Rent { iban = "DE02120300000000202051", amount = { min = 400, max = 1500 }, direction = "out" }
  rule 2 (new) -> Groceries { any_field = "FRISCHMARKT|KORNLADEN" }
  rule 3 (new) -> Salary { counterparty = "Beispiel Software", direction = "in" }
Applied: 3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeeded, 9 entries imported
$ kohle-cli list-unclassified
  entry_id  date        description               counterparty      amount  account
----------  ----------  ------------------------  --------------  --------  --------------------
         4  2026-04-20  Dinner shared with Jonas  Trattoria Roma     64.00  Unclassified Expense
```

If a rule's target has gained a child account since the rule was written, the
import fails naming it, rather than quietly falling back to the bucket and
leaving the rule disabled.

## Transfers between your own accounts

A rule that names an expense or income account describes spending or income. A
payment between two of your own accounts is neither, so a rule can instead name
the other own account with `transfer` in place of `account`. A line that
matches becomes one move between the account it was imported into and that
account, and leaves nothing in any expense, income or unclassified account:

<!-- docs: file transfer-rules.toml -->
```toml
[[rule]]
transfer = "Savings"
note = "monthly savings"
[rule.when]
iban = "DE44500105175407324931"
direction = "out"

[[rule]]
account = "Groceries"
[rule.when]
counterparty = "FRISCHMARKT"
```

<!-- docs: uses transfer-rules.toml -->
```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Savings --type asset
Added account Savings (asset) with id 3
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 4
$ kohle-cli apply-rules transfer-rules.toml --yes
2 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
  rule 1 (new) -> transfer Savings { iban = "DE44500105175407324931", direction = "out" }
  rule 2 (new) -> Groceries { counterparty = "FRISCHMARKT" }
Applied: 2 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
$ kohle-cli import-statement kohle-deutsche-bank Checking transfers.csv
Import succeeded, 2 entries imported
$ kohle-cli import-statement kohle-deutsche-bank Savings savings.csv
Import succeeded, 1 entries imported
$ kohle-cli list-unclassified
No unclassified lines
$ kohle-cli list-unmirrored-transfers
No transfers awaiting a mirror
$ kohle-cli balance Savings
unit                     quantity  price    price date      market value  status      average cost
---------------------  ----------  -------  ------------  --------------  --------  --------------
EUR                        500.00  -        -                     500.00  -                   1.00
Total (base currency)      500.00  -        -                     500.00  -                   -
```

The second import is Savings' own statement, whose row for the same 500.00
arrives a day later. Kohle recognises it as the other side of the move already
posted and absorbs it: the transfer is counted once, nothing lands in an
unclassified account, and the row needs no rule. A row is the other side of a
transfer when it goes the opposite way for exactly the same amount and is dated
within three calendar days of the move, inclusive. If both accounts have an
IBAN, the row must also name the account the money came from. When several
transfers could match, the nearest date wins. The check runs before the rules,
so a rule never classifies such a row, and the two statements can be imported
in either order: the move is dated by the statement that posted it. A row more
than three days away is not recognised and falls through to its bucket like any
other.

`list-unmirrored-transfers` shows the transfers whose other side has not
arrived, so a late or missing row stands out. It prints the entry id, date,
description, signed amount, the account the transfer was made from and its
counterpart. A transfer is listed only when its counterpart has had a statement
imported, and only when it is dated no earlier than three days before that
statement's first row, since a row older than the first import will never
arrive. A transfer to an account that has never been imported is not listed,
and neither is one whose mirror was absorbed. The command only reads: it writes
nothing and records no operation group.

### Joining a late mirror

A row more than three days from its move is not recognised, and falls through
to an unclassified bucket. `join-transfer LINE_ENTRY TRANSFER_ENTRY` corrects
that one line by hand: it names the fall-through line and the transfer, and the
line becomes the transfer's mirror. Here Savings' row arrives six days after
the move:

<!-- docs: uses transfer-rules.toml -->
```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Savings --type asset
Added account Savings (asset) with id 3
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 4
$ kohle-cli apply-rules transfer-rules.toml --yes
2 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
  rule 1 (new) -> transfer Savings { iban = "DE44500105175407324931", direction = "out" }
  rule 2 (new) -> Groceries { counterparty = "FRISCHMARKT" }
Applied: 2 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
$ kohle-cli import-statement kohle-deutsche-bank Checking transfers.csv
Import succeeded, 2 entries imported
$ kohle-cli import-statement kohle-deutsche-bank Savings savings-late.csv
Import succeeded, 1 entries imported
$ kohle-cli list-unclassified
  entry_id  date        description    counterparty      amount  account
----------  ----------  -------------  --------------  --------  -------------------
         3  2026-06-09  From checking  Erika Beispiel    500.00  Unclassified Income
$ kohle-cli join-transfer 3 1
Joined entry 3 to transfer 1
$ kohle-cli list-unclassified
No unclassified lines
$ kohle-cli balance Savings
unit                     quantity  price    price date      market value  status      average cost
---------------------  ----------  -------  ------------  --------------  --------  --------------
EUR                        500.00  -        -                     500.00  -                   1.00
Total (base currency)      500.00  -        -                     500.00  -                   -
$ kohle-cli unjoin-transfer 3
Unjoined entry 3
$ kohle-cli list-unclassified
  entry_id  date        description    counterparty      amount  account
----------  ----------  -------------  --------------  --------  -------------------
         3  2026-06-09  From checking  Erika Beispiel    500.00  Unclassified Income
```

Joining refuses a line that is not a fall-through (one a rule or a correction
has already placed), a transfer that already has a mirror, a line imported into
an account other than the transfer's counterpart, a line for a different
amount, and a line that goes the same way as the transfer. The window and the
IBAN are not checked, since overriding them is the point. The line's own
posting in the bucket is cancelled by an adjusting entry dated at the line, and
the classification becomes a mirror of that transfer, marked as corrected by
hand, which tells it apart from a mirror absorbed on import and from a
category correction. The whole join is one operation group, and nothing is
edited or deleted.

`unjoin-transfer LINE_ENTRY` reverses it. It takes the line only: another
adjusting entry puts the row's own posting back in the bucket of its direction,
and the row is a fall-through again. Because a human made the call, it stays
marked as corrected, so no later import or `classify-rules` run absorbs it
again; `join-transfer` can join it afresh. A line that a rule first sent to
another account and that was moved into the bucket by hand goes back to the
bucket, not to that account.

Kohle never decides that a rule is a transfer from the type of its target: only
the `transfer` key does. A rule written with `account = "Transfers"`, naming an
asset clearing account, keeps meaning what it always did, and a rule has exactly
one of `account` and `transfer`. Changing a rule from one to the other, or to a
different account, retires it and adds a new one, as any change to a rule does.

A transfer's counterpart must be a leaf asset or liability account outside the
`People` branch. Applying the file is refused, naming the rule, when it is an
expense or income account (which includes the unclassified buckets) or a person:

<!-- docs: file wrong-transfer.toml -->
```toml
[[rule]]
transfer = "Groceries"
[rule.when]
iban = "DE44500105175407324931"
```

<!-- docs: uses wrong-transfer.toml -->
```console
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 2
$ kohle-cli apply-rules wrong-transfer.toml --yes
Error: rule 1, transfer: 'Groceries' is an expense account; a transfer's counterpart must be an own asset or liability account
```

Rules are not tied to one account, so a transfer rule never matches a row
imported into its own counterpart: that row skips the rule and the next one is
tried. One rule file can therefore serve every statement.

### Remittances

A card payment to a money-transfer service sends euros abroad, but the other
half, the rupees that arrive, is not known until the receiving bank's statement
says so. A `remittance` rule names the account that will receive them and the
currency, and until the amount is known the euros wait in a pending bucket:

<!-- docs: file remittance-rules.toml -->
```toml
[[rule]]
remittance = "IndianBank"
unit = "INR"
[rule.when]
counterparty = "Fernweh Transfer"
```

`remittance` takes the place of `account` and `transfer`, and `unit` is required
with it and refused with the other two. The unit must be a currency other than
the base currency; kohle never assumes which. The counterpart follows the same
rules as a transfer's: a leaf asset or liability account outside `People`, and
never the pending bucket itself. A remittance rule never matches a row imported
into its own counterpart, and the kind and the unit are part of the rule's
identity, so changing either retires the rule and adds a new one.

A matched line moves from the euro account into `Pending Remittances`, an asset
account kohle creates when the first remittance is posted, so a ledger without
remittance rules gains no account. Net worth counts the euros in transit at face
value, because the pending bucket is an own account. A pending remittance is not
an unclassified line: `list-unclassified` does not show it, and
`list-pending-remittances` lists it instead, with its direction (from the sign
of the line), counterpart and unit:

<!-- docs: uses remittance-rules.toml -->
```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account IndianBank --type asset
Added account IndianBank (asset) with id 3
$ kohle-cli add-unit INR "Indian rupee" --kind currency
Added unit INR (currency) with id 1
$ kohle-cli apply-rules remittance-rules.toml --yes
1 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
  rule 1 (new) -> remittance IndianBank INR { counterparty = "Fernweh Transfer" }
Applied: 1 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
$ kohle-cli import-statement kohle-deutsche-bank Checking remittance.csv
Import succeeded, 1 entries imported
$ kohle-cli list-unclassified
No unclassified lines
$ kohle-cli list-pending-remittances
  entry_id  date        description                                                    direction      amount  account    counterpart    unit
----------  ----------  -------------------------------------------------------------  -----------  --------  ---------  -------------  ------
         1  2026-06-11  Card 0001 Fernweh Transfer 11-06-2026T09:14:02 money transfer  out           1012.00  Checking   IndianBank     INR
$ kohle-cli complete-remittance 1 90000
Completed remittance 1: 90000 INR for 1012.00 EUR
$ kohle-cli list-pending-remittances
No pending remittances
```

`complete-remittance ENTRY_ID AMOUNT` takes the entry id from that listing and
the currency that arrived, here 90,000 INR. It takes the 1,012.00 euros out of
`Pending Remittances` and puts the rupees into `IndianBank` as one lot costing
exactly 1,012.00 euros; the rate is worked out from the two amounts and never
typed. The completing entry is dated at the original line, so the lot counts
from the day the euros left even when other entries were recorded in between or
out of order. Completion is all or nothing and one step in the audit trail;
completing a remittance that is already completed, or an entry that is not a
remittance, fails and writes nothing. The classification record shows the
remittance as completed, and `reclassify` and `split-line` refuse a completed
remittance.

`classify-rules` applies remittance rules to lines that fell through, as it does
transfer rules, and shows the move as `Pending Remittances` with the counterpart
and unit in its `kind` column. `reclassify` of a pending remittance reverses it
out of the pending bucket onto the account you name, and the line then reads as
a plain correction. `split-line` is refused on a remittance, because the money
is not yet spent. Mirror recognition never absorbs a row into a pending
remittance or a pending remittance into a row.

Rupees changed back into euros work the same way in the other direction. The
rule above has no `direction`, so it matches a euro inflow from the same service
too; add `direction = "in"` or `direction = "out"` to the rule's `when` table to
restrict it to one. An incoming remittance waits in `Pending Remittances` as a
negative balance that offsets the euros received, so nothing is counted twice,
and the rupees stay in `IndianBank` until you say how many were paid out. Here
the 1,012.00 euros sent earlier have become one lot of 90,000 rupees, and
1,100.00 euros come back for them:

<!-- docs: uses remittance-rules.toml -->
```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account IndianBank --type asset
Added account IndianBank (asset) with id 3
$ kohle-cli add-unit INR "Indian rupee" --kind currency
Added unit INR (currency) with id 1
$ kohle-cli apply-rules remittance-rules.toml --yes
1 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
  rule 1 (new) -> remittance IndianBank INR { counterparty = "Fernweh Transfer" }
Applied: 1 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
$ kohle-cli import-statement kohle-deutsche-bank Checking remittance.csv
Import succeeded, 1 entries imported
$ kohle-cli complete-remittance 1 90000
Completed remittance 1: 90000 INR for 1012.00 EUR
$ kohle-cli import-statement kohle-deutsche-bank Checking remittance-back.csv
Import succeeded, 1 entries imported
$ kohle-cli list-pending-remittances
  entry_id  date        description                                       direction      amount  account    counterpart    unit
----------  ----------  ------------------------------------------------  -----------  --------  ---------  -------------  ------
         3  2026-06-20  Refund 0002 Fernweh Transfer rupees changed back  in            1100.00  Checking   IndianBank     INR
$ kohle-cli complete-remittance 3 90000
Completed remittance 3: 90000 INR for 1100.00 EUR
$ kohle-cli realised
date        account     unit      quantity    proceeds    FIFO cost    gain
----------  ----------  ------  ----------  ----------  -----------  ------
2026-06-20  IndianBank  INR       90000.00     1100.00      1012.00   88.00

Realised gain: 88.00
```

`complete-remittance` takes the same entry id and amount, but now the amount is
the rupees that left: 90,000 of them, taken out of `IndianBank` oldest lot
first and dated at the original line, against the 1,100.00 euros cleared from
`Pending Remittances`. The lot cost 1,012.00 euros, so `realised` shows a gain
of 88.00 euros under the unit `INR`, and nothing remains pending. If
`IndianBank` does not hold that many rupees, the command fails and writes
nothing.

A completion with a mistyped amount is corrected with
`uncomplete-remittance ENTRY_ID`, which reverses it by a new entry, puts the
remittance back in pending (it is listed by `list-pending-remittances` again)
and lets `complete-remittance` redo it with the right amount. The record stays
a remittance and is not marked as a human correction, since no category was
changed. [Recording entries](recording-entries.md) explains what the reversal
does to the lots and to `realised`.

## Conditions

A rule's `when` table holds one or more of these keys, and **all** of them must
hold. Patterns are Python regular expressions, matched with `search` and
case-insensitively; `(?-i:REWE)` restores case sensitivity inside a pattern.

| Key | Holds when |
|---|---|
| `description` | the pattern matches the line's description |
| `counterparty` | the pattern matches the counterparty name |
| `iban` | the counterparty IBAN equals the value, ignoring spaces and case; not a pattern |
| `amount` | the absolute amount is within `{ min = 400, max = 600 }`, bounds inclusive, either one optional |
| `direction` | `"in"` for money received, `"out"` for money spent; a zero amount is neither |
| `any_field` | the pattern matches the description, the counterparty name or the counterparty IBAN, each on its own, so `^DE89...$` means "this exact IBAN" |
| `any` | at least one of the listed tables holds (OR) |
| `not` | the table does not hold |

A line with no counterparty fails `counterparty` and `iban`, so `not` over them
holds. Amount bounds are exact decimals and are never negative: the range is on
the absolute amount, and `direction` carries the sign.

`any` is an array of tables and `not` is a table, and either may nest. Each OR
alternative, and each `not` table, must be written on a single line, because
TOML inline tables cannot span lines. This file sends either shop to
`Groceries` unless the description mentions a deposit, and keeps the rent rule:

<!-- docs: file shops.toml -->
```toml
[[rule]]
account = "Groceries"
[rule.when]
any = [
  { counterparty = "FRISCHMARKT" },
  { counterparty = "KORNLADEN", amount = { max = 200 } },
]
not = { description = "Pfand" }

[[rule]]
account = "Rent"
note = "landlord"
[rule.when]
iban = "DE02120300000000202051"
amount = { min = 400, max = 1500 }
direction = "out"
```

Applied over the first file, the rent rule is unchanged and keeps its id, the
old grocery and salary rules are retired and the new grocery rule is added:

<!-- docs: uses rules.toml shops.toml -->
```console
$ kohle-cli add-account Rent --type expense
Added account Rent (expense) with id 2
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 3
$ kohle-cli add-account Salary --type income
Added account Salary (income) with id 4
$ kohle-cli apply-rules rules.toml --yes
3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
  rule 1 (new) -> Rent { iban = "DE02120300000000202051", amount = { min = 400, max = 1500 }, direction = "out" }
  rule 2 (new) -> Groceries { any_field = "FRISCHMARKT|KORNLADEN" }
  rule 3 (new) -> Salary { counterparty = "Beispiel Software", direction = "in" }
Applied: 3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
$ kohle-cli apply-rules shops.toml --yes
1 added, 2 retired, 0 reordered, 0 note changed, 1 unchanged
  rule 1 (new) -> Groceries { any = [{ counterparty = "FRISCHMARKT" }, { counterparty = "KORNLADEN", amount = { max = 200 } }], not = { description = "Pfand" } }
  id 2 -> Groceries { any_field = "FRISCHMARKT|KORNLADEN" } (retired)
  id 3 -> Salary { counterparty = "Beispiel Software", direction = "in" } (retired)
Applied: 1 added, 2 retired, 0 reordered, 0 note changed, 1 unchanged
```

## The rule file

`show-rules` prints the whole rule set as TOML, in evaluation order. It is the
same layout that `apply-rules` and `edit-rules` read, so the output of one is a
valid input to the others. Rule ids never appear in the file:

<!-- docs: uses rules.toml -->
```console
$ kohle-cli add-account Rent --type expense
Added account Rent (expense) with id 2
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 3
$ kohle-cli add-account Salary --type income
Added account Salary (income) with id 4
$ kohle-cli apply-rules rules.toml --yes
3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
  rule 1 (new) -> Rent { iban = "DE02120300000000202051", amount = { min = 400, max = 1500 }, direction = "out" }
  rule 2 (new) -> Groceries { any_field = "FRISCHMARKT|KORNLADEN" }
  rule 3 (new) -> Salary { counterparty = "Beispiel Software", direction = "in" }
Applied: 3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
$ kohle-cli show-rules
# kohle classification rules, in priority order: the first rule that matches
# a line wins. Keys under [rule.when] must all hold; any = [...] needs one of
# its tables to hold; not = {...} must not hold.
# Leave `base` as it is: apply-rules uses it to refuse if the stored rules
# changed after this file was rendered.
base = "9fd93fc14dd9428f"

[[rule]]
account = "Rent"
note = "landlord"
[rule.when]
iban = "DE02120300000000202051"
amount = { min = 400, max = 1500 }
direction = "out"

[[rule]]
account = "Groceries"
[rule.when]
any_field = "FRISCHMARKT|KORNLADEN"

[[rule]]
account = "Salary"
[rule.when]
counterparty = "Beispiel Software"
direction = "in"
```

Each `[[rule]]` has an `account`, an optional `note` and a `[rule.when]` table.
A rule with no conditions, an unknown key, an unknown or non-leaf account or an
invalid pattern is refused, naming the rule and key, for example
`rule 2, when.any[1].iban: ...`.

`base` fingerprints the rule set the file was rendered from. A file whose `base`
no longer matches the stored rules is refused, so that you do not overwrite a
change made since. Delete the `base` line to apply the file over the current
rules anyway. A file with no `base` line, like `rules.toml` above, is always
applied over what is stored.

Rules have a content-based identity. A rule whose conditions and account are
unchanged keeps its id wherever it moves in the file, and a note-only edit
updates the note. Any other change to the conditions or the account retires the
old rule and adds a new one, so a past classification keeps naming the
conditions that made it. Deleting a rule from the file retires it the same way,
and a retired rule is never revived: a file that restores its content adds a
new rule. Applying the output of `show-rules` reports `No changes`, and two
rules with the same conditions and account in one file are refused. The whole
apply is one audit-trail group, or nothing.

`edit-rules` opens the same file in `$VISUAL` or `$EDITOR`, then shows the same
summary and asks before applying. Because it needs an editor it cannot be run
in the examples on this page:

<!-- docs: illustration -->
```sh
$ kohle-cli edit-rules
```

Saving nothing prints `No changes; nothing applied`. A mistake reopens the
editor with the problem in a banner at the top of the file, and quitting without
saving aborts. If the stored rules changed while you were editing, your text is
saved to a file named in the error rather than lost.

## Rules for lines already imported

Rules written after an import do not reach lines already in the buckets.
`classify-rules` runs the current rules over them and moves the ones that now
match. It prints a preview, then asks `Move N line(s)?`; `--yes` skips the
question:

<!-- docs: uses rules.toml -->
```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Rent --type expense
Added account Rent (expense) with id 3
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 4
$ kohle-cli add-account Salary --type income
Added account Salary (income) with id 5
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeeded, 9 entries imported
$ kohle-cli apply-rules rules.toml --yes
3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
  rule 1 (new) -> Rent { iban = "DE02120300000000202051", amount = { min = 400, max = 1500 }, direction = "out" }
  rule 2 (new) -> Groceries { any_field = "FRISCHMARKT|KORNLADEN" }
  rule 3 (new) -> Salary { counterparty = "Beispiel Software", direction = "in" }
Applied: 3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
$ kohle-cli classify-rules --yes
  entry_id  date        description                                           amount  from                  to           rule
----------  ----------  --------------------------------------------------  --------  --------------------  ---------  ------
         1  2026-04-01  Rent April                                           -900.00  Unclassified Expense  Rent            1
         2  2026-04-06  Card 0001 FRISCHMARKT 06-04-2026T17:20:41 purchase    -38.60  Unclassified Expense  Groceries       2
         3  2026-04-14  Card 0001 KORNLADEN 14-04-2026T10:05:09 purchase      -21.45  Unclassified Expense  Groceries       2
         5  2026-04-28  Salary April                                         2600.00  Unclassified Income   Salary          3
         6  2026-05-01  Rent May                                             -900.00  Unclassified Expense  Rent            1
         7  2026-05-08  Card 0001 FRISCHMARKT 08-05-2026T16:48:33 purchase    -45.20  Unclassified Expense  Groceries       2
         8  2026-05-21  Card 0001 KORNLADEN 21-05-2026T11:12:50 purchase      -19.80  Unclassified Expense  Groceries       2
         9  2026-05-28  Salary May                                           2600.00  Unclassified Income   Salary          3
Moved 8 line(s)
$ kohle-cli list-unclassified
  entry_id  date        description               counterparty      amount  account
----------  ----------  ------------------------  --------------  --------  --------------------
         4  2026-04-20  Dinner shared with Jonas  Trattoria Roma     64.00  Unclassified Expense
$ kohle-cli classify-rules --yes
No unclassified line matches a rule
```

Only untouched fall-throughs are considered. Lines already matched by a rule,
corrected by hand, moved by an earlier run or split are left alone. Each move
posts a reversing pair dated at the original entry, as `reclassify` does. The
move is recorded against the rule that made it and does not count as a
correction, so a rule's move is never mistaken for a human's.

Transfer rules are ordinary entries in the same ordered list, so the first rule
that matches a line wins, and `classify-rules` applies them to the lines left in
the buckets as it does any other rule. A line that matches one becomes a move to
the rule's account, and the same run absorbs the other side of that move: the
untouched fall-through in the counterpart account that goes the opposite way for
the same amount within three days. The preview lists both lines and gains a
`kind` column, which is `transfer` for the move and `mirror of N` for the
absorbed line, where N is the entry id of the move's statement line. A mirror
shows `-` under `rule`, because no rule moved it. Plans made only of category
moves have no `kind` column.

Mirror recognition still runs before any rule: a fall-through that is the other
side of a transfer already posted is absorbed even when a category rule would
also match it, and with a transfer rule on each side the earlier line makes the
move and absorbs the other. `Moved N line(s)` counts the mirrors as well.
Lines a rule or a human has already classified are never touched, and the whole
run is all or nothing and one audit-trail group.

Retiring or editing a transfer rule never undoes a move already posted. Only
`classify-rules` moves anything, so a changed rule file changes nothing until it
is run.

## Correcting a line by hand

`reclassify` moves a line onto a different account, whether a wrong rule put it
there or it fell through to a bucket. It takes the entry id that
`list-unclassified` prints in its first column:

<!-- docs: uses rules.toml -->
```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Rent --type expense
Added account Rent (expense) with id 3
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 4
$ kohle-cli add-account Salary --type income
Added account Salary (income) with id 5
$ kohle-cli add-account Dining --type expense
Added account Dining (expense) with id 6
$ kohle-cli apply-rules rules.toml --yes
3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
  rule 1 (new) -> Rent { iban = "DE02120300000000202051", amount = { min = 400, max = 1500 }, direction = "out" }
  rule 2 (new) -> Groceries { any_field = "FRISCHMARKT|KORNLADEN" }
  rule 3 (new) -> Salary { counterparty = "Beispiel Software", direction = "in" }
Applied: 3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeeded, 9 entries imported
$ kohle-cli reclassify 4 Dining
Reclassified entry 4 to Dining
$ kohle-cli list-unclassified
No unclassified lines
```

The ledger is append-only, so the original entry is never edited, voided or
deleted. Instead a reversing pair is posted, dated the same day as the original:
the wrong account is credited and the right one debited, for the original
amount. The classification record moves with it. The final account becomes the
new one and the line is marked corrected, while the proposed account and the
rule that matched stay as they were, because they record what the engine got
wrong. Reclassifying a corrected line again reverses out of its current account,
not its original proposal.

### Correcting a transfer

`reclassify` knows about transfers, so a correction never double counts and
never leaves half of a pair undone. The target account decides the path: an
asset or liability account outside People is an own account, so the line becomes
a transfer to it, exactly as a transfer rule would have made it, and the
fall-through of that account that mirrors it is absorbed. Any other target is a
category, as before.

- Reclassifying a transfer to a category, or to a different own account, first
  puts its mirror back in its bucket, then moves the transfer. The mirror goes
  back as an ordinary fall-through, and a mirror that a human joined stays
  marked corrected. All of it is adjusting entries dated at each line's own
  date, all or nothing, in one audit-trail group.
- The mirror row of a transfer cannot be reclassified. Run `unjoin-transfer`
  on it first; the error says so.
- A transfer cannot target the pending bucket, or the account the line itself
  was imported into.
- The classification record shows what happened. A line reclassified onto an own
  account is a `transfer` marked corrected, which tells it apart from a
  rule-made transfer, and from a category correction.

`split-line` is refused on a transfer and on the mirror row of one, with an
error naming which it is. A transfer is a move between your own accounts, so
there is nothing to share out. Reclassify the line to a category first if it
really was a shared bill.

An unknown entry id, an unknown target account or a target with sub-accounts
fails with an error rather than a traceback:

<!-- docs: uses rules.toml -->
```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeeded, 9 entries imported
$ kohle-cli reclassify 4 Dining
Error: Account 'Dining' not found
$ kohle-cli reclassify 99 Dining
Error: Journal entry id 99 has no classification record; only imported cash lines can be reclassified or split
```

A shared bill such as the dinner can also be split with someone instead of
moved whole; see [People and splitting](people-and-splitting.md).
