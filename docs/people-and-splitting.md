# People and splitting

Sharing costs with other people and settling up.

Some of what you pay is not only yours: a dinner you cover and share, a trip
where one person books everything. kohle keeps your own share as expense and
the rest as money someone owes you, so your spending is not overstated and the
debt is not forgotten. The examples use the shared dinner in `statement.csv`,
the fictional Deutsche Bank export from
[Import and classification](import-and-classification.md); on this page nothing
is classified, so the dinner is still in `Unclassified Expense`.

## People are accounts

A person is an ordinary account under `People`, the root every fresh ledger
starts with. It is an `asset` account because what a person owes you is
something you are owed. Create one with `add-account` and `--parent People`:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeded, 9 entries imported
$ kohle-cli add-account Jonas --type asset --parent People
Added account Jonas (asset) with id 5
$ kohle-cli list-accounts
account               type     iban
--------------------  -------  ------
Checking              asset    -
People/               asset    -
|- Jonas              asset    -
Unclassified Expense  expense  -
Unclassified Income   income   -
```

A person's balance is what they owe you; a negative balance means you owe them.
`net-worth` counts the `People` branch as receivables, apart from your own
accounts.

## Splitting an imported line

`split-line` divides a line that is already imported between your own share and
one or more people. `list-unclassified` prints the entry id it takes, in its
first column, and the dinner is entry 4. `--mine` states your share and each
`--share PERSON:AMOUNT` adds a person's, repeated for more than one person:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeded, 9 entries imported
$ kohle-cli add-account Jonas --type asset --parent People
Added account Jonas (asset) with id 5
$ kohle-cli split-line 4 --mine 32 --share Jonas:32
Split entry 4: 32 own, Jonas 32
$ kohle-cli who-owes-what
person    unit      balance
--------  ------  ---------
Jonas     EUR         32.00
$ kohle-cli balance Jonas
unit                     quantity  price    price date      market value  status      average cost
---------------------  ----------  -------  ------------  --------------  --------  --------------
EUR                         32.00  -        -                      32.00  -                   1.00
Total (base currency)       32.00  -        -                      32.00  -                   -
$ kohle-cli entries-in-period Jonas 2026-04-01 2026-06-01
  entry_id  date        description                      counterparty    side      quantity  unit      value
----------  ----------  -------------------------------  --------------  ------  ----------  ------  -------
        10  2026-04-20  Split: Dinner shared with Jonas  -               dr           32.00  EUR       32.00
```

The 64 euro dinner now leaves 32 as your expense and 32 as a receivable from
Jonas. The original import is not edited, voided or deleted. The split is a
further, adjusting entry dated the same day, which is the entry
`entries-in-period` shows against Jonas.

The shares must add up to the line's amount exactly. Only imported lines can be
split, because a line entered by hand with `record` or `record-split` has no
classification to split against. Each of these fails with an error rather than
a traceback, and nothing is changed:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeded, 9 entries imported
$ kohle-cli add-account Jonas --type asset --parent People
Added account Jonas (asset) with id 5
$ kohle-cli add-account Mira --type asset --parent People
Added account Mira (asset) with id 6
$ kohle-cli split-line 4 --mine 32 --share Jonas:40
Error: Split shares sum to 72, not the line's 64.00000000
$ kohle-cli split-line 4 --mine 32 --share Checking:32
Error: Account 'Checking' is not under the People branch
$ kohle-cli split-line 4 --mine 32 --share Nobody:32
Error: Account 'Nobody' not found
$ kohle-cli split-line 99 --mine 32 --share Jonas:32
Error: Journal entry id 99 has no classification record; only imported cash lines can be reclassified or split
$ kohle-cli record 2026-06-01 "Cash from Jonas" 10 --from Jonas --to Checking
Recorded 10 EUR: credited Jonas, debited Checking
$ kohle-cli split-line 10 --mine 5 --share Jonas:5
Error: Journal entry id 10 has no classification record; only imported cash lines can be reclassified or split
$ kohle-cli split-line 4 --mine 24 --share Jonas:20 --share Mira:20
Split entry 4: 24 own, Jonas 20, Mira 20
$ kohle-cli who-owes-what
person    unit      balance
--------  ------  ---------
Jonas     EUR         10.00
Mira      EUR         20.00
```

The last command shows a split between two people, and the figures also include
the 10 euros Jonas paid in with `record`, which reduces what he owes.

A line that was reclassified before it was split is split out of the account it
was moved to, not out of its original bucket. The other order does not work:
`reclassify` refuses an entry that is already split, so correct the account
first and split afterwards.

## Changing or undoing a split

Running `split-line` again on the same entry replaces the allocation. Nothing
has to be undone first: the old split is reversed and the new one posted in a
single step, so a failure anywhere leaves the previous split in place.
`unsplit-line` removes a split entirely, and a second one finds nothing to undo:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeded, 9 entries imported
$ kohle-cli add-account Jonas --type asset --parent People
Added account Jonas (asset) with id 5
$ kohle-cli split-line 4 --mine 32 --share Jonas:32
Split entry 4: 32 own, Jonas 32
$ kohle-cli split-line 4 --mine 40 --share Jonas:24
Split entry 4: 40 own, Jonas 24
$ kohle-cli who-owes-what
person    unit      balance
--------  ------  ---------
Jonas     EUR         24.00
$ kohle-cli unsplit-line 4
Undid the split of entry 4
$ kohle-cli who-owes-what
person    unit      balance
--------  ------  ---------
Jonas     EUR          0.00
$ kohle-cli unsplit-line 4
Error: Journal entry id 4 has no current split
```

The ledger is append-only, so neither command edits anything. `unsplit-line`
posts a mirror of the split's current adjusting entry with every side flipped,
which brings the expense and the person's balance back to what they were before
the split. The original import, the first split and the correction all stay
readable in `entries-in-period` and in the audit trail that `list-operations`
prints.

## Trips and other groups

A group is a label, such as a trip, that ties several splits together. A group
is created explicitly with `add-group` and looked up strictly: naming one that
does not exist fails, so a typo cannot quietly start a second group with a
similar spelling. `--group` goes on `split-line`:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeded, 9 entries imported
$ kohle-cli add-account Jonas --type asset --parent People
Added account Jonas (asset) with id 5
$ kohle-cli add-account Mira --type asset --parent People
Added account Mira (asset) with id 6
$ kohle-cli add-group "Spring trip"
Added split group Spring trip with id 1
$ kohle-cli add-group "Spring trip"
Error: Split group Spring trip already exists
$ kohle-cli split-line 4 --mine 32 --share Jonas:32 --group "Spring trip"
Split entry 4: 32 own, Jonas 32
$ kohle-cli split-line 3 --mine 10.45 --share Mira:11 --group "Summer"
Error: Split group 'Summer' not found
$ kohle-cli split-line 3 --mine 10.45 --share Mira:11 --group "Spring trip"
Split entry 3: 10.45 own, Mira 11
$ kohle-cli split-line 7 --mine 30.20 --share Jonas:15
Split entry 7: 30.20 own, Jonas 15
```

Grouping is additive: a split without `--group` works as it always did, and its
amounts simply belong to no group. `--group` is authoritative on every run of
`split-line`, so leaving it out clears the split's group and naming another one
moves it.

## Who owes what

`who-owes-what` lists the net balance of every account under `People`, the same
figure `balance` gives for one person, for everyone at once. A person who has
never been split against shows `-`, which is different from a settled
person's `0.00`, where lines exist and happen to cancel out. `--by-group`
breaks the view down into one block per group, including a group with no splits
yet, so it also lists your groups:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeded, 9 entries imported
$ kohle-cli add-account Jonas --type asset --parent People
Added account Jonas (asset) with id 5
$ kohle-cli add-account Mira --type asset --parent People
Added account Mira (asset) with id 6
$ kohle-cli add-group "Spring trip"
Added split group Spring trip with id 1
$ kohle-cli split-line 4 --mine 32 --share Jonas:32 --group "Spring trip"
Split entry 4: 32 own, Jonas 32
$ kohle-cli split-line 3 --mine 10.45 --share Mira:11 --group "Spring trip"
Split entry 3: 10.45 own, Mira 11
$ kohle-cli split-line 7 --mine 30.20 --share Jonas:15
Split entry 7: 30.20 own, Jonas 15
$ kohle-cli who-owes-what
person    unit      balance
--------  ------  ---------
Jonas     EUR         47.00
Mira      EUR         11.00
$ kohle-cli who-owes-what --by-group

Spring trip
person    unit      from splits
--------  ------  -------------
Jonas     EUR             32.00
Mira      EUR             11.00

Note: group figures are historical allocations, not settlement-adjusted balances.
```

Jonas owes 47 in all, and 32 of that came from the trip. The `from splits`
column sums the group's current splits only, so it is what the trip cost each
person, not a live balance. If Jonas has paid you back since, `who-owes-what`
shows it and the group figure does not, which is why the two columns are named
differently. Splits with no group appear in neither block.

## Settling up

`settle-up` suggests the fewest transfers that bring every person's current
balance to zero. A balance that is already zero needs none:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeded, 9 entries imported
$ kohle-cli add-account Jonas --type asset --parent People
Added account Jonas (asset) with id 5
$ kohle-cli add-account Mira --type asset --parent People
Added account Mira (asset) with id 6
$ kohle-cli settle-up
No transfers needed
$ kohle-cli split-line 4 --mine 32 --share Jonas:32
Split entry 4: 32 own, Jonas 32
$ kohle-cli split-line 3 --mine 10.45 --share Mira:11
Split entry 3: 10.45 own, Mira 11
$ kohle-cli settle-up
payer    payee    unit      quantity
-------  -------  ------  ----------
Jonas    you      EUR          32.00
Mira     you      EUR          11.00
Settle with: kohle-cli record <date> "<description>" 32.00 --from Jonas --to <your account>
Settle with: kohle-cli record <date> "<description>" 11.00 --from Mira --to <your account>
```

`you` stands for your own side. kohle cannot know which of your accounts
received the money, so the `Settle with` line leaves `<your account>`, the date
and the description for you to fill in. `settle-up` writes nothing: it reads the
current balances afresh each time. Recording the payment is a normal
[`record`](recording-entries.md), after which the balance, and the suggestion,
update:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeded, 9 entries imported
$ kohle-cli add-account Jonas --type asset --parent People
Added account Jonas (asset) with id 5
$ kohle-cli add-account Mira --type asset --parent People
Added account Mira (asset) with id 6
$ kohle-cli split-line 4 --mine 32 --share Jonas:32
Split entry 4: 32 own, Jonas 32
$ kohle-cli split-line 3 --mine 10.45 --share Mira:11
Split entry 3: 10.45 own, Mira 11
$ kohle-cli record 2026-06-01 "Jonas pays his share" 32 --from Jonas --to Checking
Recorded 32 EUR: credited Jonas, debited Checking
$ kohle-cli who-owes-what
person    unit      balance
--------  ------  ---------
Jonas     EUR          0.00
Mira      EUR         11.00
$ kohle-cli settle-up
payer    payee    unit      quantity
-------  -------  ------  ----------
Mira     you      EUR          11.00
Settle with: kohle-cli record <date> "<description>" 11.00 --from Mira --to <your account>
```

Transfers are netted, so people who cancel through each other need fewer
payments than there are debts. Here Jonas owes 20 and Mira, who paid in 30
against a 20 share, is owed 10; Jonas settles with both at once, and a negative
balance turns `you` into the payer when it is yours to pay:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeded, 9 entries imported
$ kohle-cli add-account Jonas --type asset --parent People
Added account Jonas (asset) with id 5
$ kohle-cli add-account Mira --type asset --parent People
Added account Mira (asset) with id 6
$ kohle-cli split-line 4 --mine 24 --share Jonas:20 --share Mira:20
Split entry 4: 24 own, Jonas 20, Mira 20
$ kohle-cli record 2026-06-01 "Mira pays" 30 --from Mira --to Checking
Recorded 30 EUR: credited Mira, debited Checking
$ kohle-cli who-owes-what
person    unit      balance
--------  ------  ---------
Jonas     EUR         20.00
Mira      EUR        -10.00
$ kohle-cli settle-up
payer    payee    unit      quantity
-------  -------  ------  ----------
Jonas    Mira     EUR          10.00
Jonas    you      EUR          10.00
Settle with: kohle-cli record <date> "<description>" 10.00 --from Jonas --to Mira
Settle with: kohle-cli record <date> "<description>" 10.00 --from Jonas --to <your account>
```

Netting runs once per unit, so euros and shares are never combined into one
suggestion.

`--group` restricts the suggestion to the people in a group while keeping each
of their full, current balances, not the group's historical figure. With the
trip above, Jonas still settles the 47 he owes in total, and your own position is
recomputed as the negation of just that subset. An unknown group fails
rather than suggesting nothing:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeded, 9 entries imported
$ kohle-cli add-account Jonas --type asset --parent People
Added account Jonas (asset) with id 5
$ kohle-cli add-account Mira --type asset --parent People
Added account Mira (asset) with id 6
$ kohle-cli add-group "Spring trip"
Added split group Spring trip with id 1
$ kohle-cli split-line 4 --mine 32 --share Jonas:32 --group "Spring trip"
Split entry 4: 32 own, Jonas 32
$ kohle-cli split-line 7 --mine 30.20 --share Jonas:15
Split entry 7: 30.20 own, Jonas 15
$ kohle-cli settle-up --group "Spring trip"
payer    payee    unit      quantity
-------  -------  ------  ----------
Jonas    you      EUR          47.00
Settle with: kohle-cli record <date> "<description>" 47.00 --from Jonas --to <your account>
$ kohle-cli settle-up --group "Summer"
Error: Split group 'Summer' not found
```
