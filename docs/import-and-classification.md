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
