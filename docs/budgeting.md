# Budgeting

Caps are estimates of what an expense account should cost over a period, and
`budget` compares them with what was spent. A deviation is information, not an
error: nothing blocks an entry or a purchase. Caps are stored in the ledger as
data and travel with snapshots (see [Several devices](several-devices.md)), so
they are never a setting of one device.

The examples use fictional accounts. `Checking` pays for `Groceries`,
`Restaurants` and `Internet`, and for `Fitness`, which never gets a cap. The
bank statement is `statement.csv`, shipped with these docs and imported as
described on [Import and classification](import-and-classification.md). Today
is 17 June 2026 throughout.

## Caps

A cap is an amount in euros plus a recurrence. The recurrence is written in the
same rule vocabulary as `set-sampling-rules`, which is listed under
[Sampling rules](reports.md#sampling-rules), and it defines the cap's period:
`day 1` gives calendar months, and `workday 25` runs from payday to payday. An
`every N months from DATE` rule gives periods of N months in step with the date.
`last day` is accepted but would start each period on the last day of a month,
which is rarely what you want.

Any expense account, leaf or parent, may be capped, and a cap on a parent
covers its whole subtree. Caps on a parent and a child are checked
independently and need not add up. A total cap is a parent account you create
and cap. Income, asset and liability accounts, People accounts and
`Unclassified Expense` are refused: that account has its own row in the report.
An amount is 0 or more, and 0 makes any spending an overshoot.

`set-cap ACCOUNT AMOUNT RULE --from DATE` sets a cap, `end-cap ACCOUNT --from
DATE` records "no cap" from a date, and `list-caps` shows every account's full
history. The history is sorted by account name and then oldest first, and an
`end-cap` entry shows `-` and `no cap`. An invalid account, amount, rule or date
writes nothing, and the error names the bad part and lists the valid choices.
Each change is one operation in `list-operations`.

A negative amount has to follow `--` so it is not read as an option, and
`--from` must then come before the `--`:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 3
$ kohle-cli add-account Restaurants --type expense
Added account Restaurants (expense) with id 4
$ kohle-cli add-account Internet --type expense
Added account Internet (expense) with id 5
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeeded, 9 entries imported
$ kohle-cli set-cap Groceries 300 "day 1" --from 2026-01-01
Set cap on Groceries from 2026-01-01: 300.00, day 1
$ kohle-cli set-cap Groceries 400 "day 1" --from 2026-03-10
Set cap on Groceries from 2026-03-10: 400.00, day 1
$ kohle-cli set-cap Restaurants 150 "workday 25" --from 2026-01-01
Set cap on Restaurants from 2026-01-01: 150.00, workday 25
$ kohle-cli set-cap Internet 39.90 "every 3 months from 2026-01-15" --from 2026-01-01
Set cap on Internet from 2026-01-01: 39.90, every 3 months from 2026-01-15
$ kohle-cli end-cap Restaurants --from 2026-06-01
Ended cap on Restaurants from 2026-06-01
$ kohle-cli list-caps
account      from           cap  rule
-----------  ----------  ------  ------------------------------
Groceries    2026-01-01  300.00  day 1
Groceries    2026-03-10  400.00  day 1
Internet     2026-01-01   39.90  every 3 months from 2026-01-15
Restaurants  2026-01-01  150.00  workday 25
Restaurants  2026-06-01    -     no cap
$ kohle-cli set-cap Checking 100 "day 1" --from 2026-01-01
Error: cannot cap 'Checking': it is an asset account; accounts that can be capped: Groceries, Internet, Restaurants
$ kohle-cli set-cap "Unclassified Expense" 100 "day 1" --from 2026-01-01
Error: cannot cap 'Unclassified Expense': it has its own row in budget; accounts that can be capped: Groceries, Internet, Restaurants
$ kohle-cli set-cap Groceries 100 "day 40" --from 2026-01-01
Error: invalid rule 'day 40'; expected day N with N from 1 to 31
$ kohle-cli end-cap Internet --from 2025-12-01
Error: Internet has no cap in force on 2025-12-01; list-caps shows its history
$ kohle-cli set-cap Groceries --from 2026-01-01 -- -5 "day 1"
Error: invalid cap amount -5; expected a number of 0 or more
```

## Effective dating

Caps are an effective-dated history per account. `--from` is required, takes a
date only (there is no `start` here, unlike `move-state`) and may be in the
future. An account has one entry in force at a time. Repeating a date replaces
that entry, which is how you correct a mistake. `end-cap` is refused when the
account has no cap in force on that date, as the `end-cap` error above
shows.

## Periods

A period runs from one occurrence of the cap's rule to the day before the next.
The shifting kinds (`workday N`, `<nth> <weekday>` and `last workday`) move
under the Bundesland in force, see [Bundesland history](reports.md#bundesland-history).
`budget` refuses and points to `move-state --from start <code>` when a cap uses
one and the ledger has no `start` entry. A ledger made with `init` always has
one, and caps using only the other kinds work without it.

An entry taking effect at D cuts: it ends the running period on D-1 and starts a
new one at D, which ends the day before the new rule's next occurrence after D.
A cap's first period starts at its D the same way. A period cut short by D, or
one that starts off an occurrence of the rule, is marked `short`, and its cap is
not prorated. In the first report below the Groceries history from the `list-caps`
output above gives a March of 1 to 9 March (short, cap 300) and 10 to 31 March
(short, cap 400), and then a full April at 400. `Internet` shows the other kind:
its rule falls on the 15th of January, April, July and October, so its first
period is 1 to 14 January, short, and every later one runs from the 15th.

An entry that falls on an occurrence of the running rule is not a cut, and an
entry identical to the one before it (the same amount and rule, or two
`end-cap`s) is listed but cuts nothing. Repeating the earlier cap at a
mistaken date therefore repairs the history without doubling the cap. Here the
raise was meant to start on 1 March, so a new entry at that date makes the
10 March entry a repeat, and March becomes one period:

```console
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 2
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 3
$ kohle-cli set-cap Groceries 300 "day 1" --from 2026-01-01
Set cap on Groceries from 2026-01-01: 300.00, day 1
$ kohle-cli set-cap Groceries 400 "day 1" --from 2026-03-10
Set cap on Groceries from 2026-03-10: 400.00, day 1
$ kohle-cli record 2026-03-04 "Weekly shop" 112 --from Checking --to Groceries
Recorded 112 EUR: credited Checking, debited Groceries
$ kohle-cli record 2026-03-20 "Weekly shop" 289.90 --from Checking --to Groceries
Recorded 289.90 EUR: credited Checking, debited Groceries
$ kohle-cli budget --from 2026-03-01 --to 2026-04-30
account               from        to             cap    spent    over/under  note
--------------------  ----------  ----------  ------  -------  ------------  ------
Groceries             2026-03-01  2026-03-09  300.00   112.00       -188.00  short
Groceries             2026-03-10  2026-03-31  400.00   289.90       -110.10  short
Groceries             2026-04-01  2026-04-30  400.00     0.00       -400.00  -
Unclassified Expense  2026-03-01  2026-04-30    -        0.00          -     -
(uncapped)            2026-03-01  2026-04-30    -        0.00          -     -
$ kohle-cli set-cap Groceries 400 "day 1" --from 2026-03-01
Set cap on Groceries from 2026-03-01: 400.00, day 1
$ kohle-cli list-caps
account    from           cap  rule
---------  ----------  ------  ------
Groceries  2026-01-01  300.00  day 1
Groceries  2026-03-01  400.00  day 1
Groceries  2026-03-10  400.00  day 1
$ kohle-cli budget --from 2026-03-01 --to 2026-04-30
account               from        to             cap    spent    over/under  note
--------------------  ----------  ----------  ------  -------  ------------  ------
Groceries             2026-03-01  2026-03-31  400.00   401.90          1.90  over
Groceries             2026-04-01  2026-04-30  400.00     0.00       -400.00  -
Unclassified Expense  2026-03-01  2026-04-30    -        0.00          -     -
(uncapped)            2026-03-01  2026-04-30    -        0.00          -     -
```

Months-based rules clamp to the length of each month without drifting:
`every 1 months from 2026-01-31` gives 31 January to 27 February, then 28
February to 30 March, then 31 March to 29 April.

## The budget report

`budget` prints one row per period of every cap that overlaps the range, then
two rows for the spending that no cap covers. `--to` defaults to today and may
not be after it, and `--from` defaults to 1 January of `--to`'s year and may not
be after `--to`. Both are usage errors otherwise. Every period that overlaps the
range is shown whole, with all its spending, and is not clipped to the range.
Periods starting after today are not shown. Rows come by account, then period
start.

The session below adds spending to the caps above: groceries, a refund, two
restaurant meals, a gym fee that no cap covers, and the unclassified lines from
the imported statement. The ranges in the second and third reports are narrower
than the periods they show, so those periods come out whole all the same:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 3
$ kohle-cli add-account Restaurants --type expense
Added account Restaurants (expense) with id 4
$ kohle-cli add-account Internet --type expense
Added account Internet (expense) with id 5
$ kohle-cli add-account Fitness --type expense
Added account Fitness (expense) with id 6
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeeded, 9 entries imported
$ kohle-cli set-cap Groceries 300 "day 1" --from 2026-01-01
Set cap on Groceries from 2026-01-01: 300.00, day 1
$ kohle-cli set-cap Groceries 400 "day 1" --from 2026-03-10
Set cap on Groceries from 2026-03-10: 400.00, day 1
$ kohle-cli set-cap Restaurants 150 "workday 25" --from 2026-01-01
Set cap on Restaurants from 2026-01-01: 150.00, workday 25
$ kohle-cli set-cap Internet 39.90 "every 3 months from 2026-01-15" --from 2026-01-01
Set cap on Internet from 2026-01-01: 39.90, every 3 months from 2026-01-15
$ kohle-cli end-cap Restaurants --from 2026-06-01
Ended cap on Restaurants from 2026-06-01
$ kohle-cli record 2026-01-10 "Weekly shop" 320.50 --from Checking --to Groceries
Recorded 320.50 EUR: credited Checking, debited Groceries
$ kohle-cli record 2026-03-04 "Weekly shop" 112 --from Checking --to Groceries
Recorded 112 EUR: credited Checking, debited Groceries
$ kohle-cli record 2026-03-20 "Weekly shop" 289.90 --from Checking --to Groceries
Recorded 289.90 EUR: credited Checking, debited Groceries
$ kohle-cli record 2026-04-14 "Returned goods" 15 --from Groceries --to Checking
Recorded 15 EUR: credited Groceries, debited Checking
$ kohle-cli record 2026-06-05 "Weekly shop" 150 --from Checking --to Groceries
Recorded 150 EUR: credited Checking, debited Groceries
$ kohle-cli record 2026-06-12 "Weekly shop" 80 --from Checking --to Groceries
Recorded 80 EUR: credited Checking, debited Groceries
$ kohle-cli record 2026-02-20 "Dinner out" 170 --from Checking --to Restaurants
Recorded 170 EUR: credited Checking, debited Restaurants
$ kohle-cli record 2026-05-10 "Lunch out" 60 --from Checking --to Restaurants
Recorded 60 EUR: credited Checking, debited Restaurants
$ kohle-cli record 2026-01-20 "Internet bill" 39.90 --from Checking --to Internet
Recorded 39.90 EUR: credited Checking, debited Internet
$ kohle-cli record 2026-06-02 "Gym" 30 --from Checking --to Fitness
Recorded 30 EUR: credited Checking, debited Fitness
$ kohle-cli budget
account               from        to             cap    spent    over/under  note
--------------------  ----------  ----------  ------  -------  ------------  --------------------
Groceries             2026-01-01  2026-01-31  300.00   320.50         20.50  over
Groceries             2026-02-01  2026-02-28  300.00     0.00       -300.00  -
Groceries             2026-03-01  2026-03-09  300.00   112.00       -188.00  short
Groceries             2026-03-10  2026-03-31  400.00   289.90       -110.10  short
Groceries             2026-04-01  2026-04-30  400.00   -15.00       -415.00  -
Groceries             2026-05-01  2026-05-31  400.00     0.00       -400.00  -
Groceries             2026-06-01  2026-06-30  400.00   230.00       -170.00  partial day 17 of 30
Internet              2026-01-01  2026-01-14   39.90     0.00        -39.90  short
Internet              2026-01-15  2026-04-14   39.90    39.90          0.00  -
Internet              2026-04-15  2026-07-14   39.90     0.00        -39.90  partial day 64 of 91
Restaurants           2026-01-01  2026-01-22  150.00     0.00       -150.00  short
Restaurants           2026-01-23  2026-02-24  150.00   170.00         20.00  over
Restaurants           2026-02-25  2026-03-24  150.00     0.00       -150.00  -
Restaurants           2026-03-25  2026-04-23  150.00     0.00       -150.00  -
Restaurants           2026-04-24  2026-05-21  150.00    60.00        -90.00  -
Restaurants           2026-05-22  2026-05-31  150.00     0.00       -150.00  short
Unclassified Expense  2026-01-01  2026-06-17    -     1989.05          -     -
(uncapped)            2026-01-01  2026-06-17    -       30.00          -     -
$ kohle-cli budget --from 2026-03-01 --to 2026-04-30
account               from        to             cap    spent    over/under  note
--------------------  ----------  ----------  ------  -------  ------------  --------------------
Groceries             2026-03-01  2026-03-09  300.00   112.00       -188.00  short
Groceries             2026-03-10  2026-03-31  400.00   289.90       -110.10  short
Groceries             2026-04-01  2026-04-30  400.00   -15.00       -415.00  -
Internet              2026-01-15  2026-04-14   39.90    39.90          0.00  -
Internet              2026-04-15  2026-07-14   39.90     0.00        -39.90  partial day 64 of 91
Restaurants           2026-02-25  2026-03-24  150.00     0.00       -150.00  -
Restaurants           2026-03-25  2026-04-23  150.00     0.00       -150.00  -
Restaurants           2026-04-24  2026-05-21  150.00    60.00        -90.00  -
Unclassified Expense  2026-03-01  2026-04-30    -     1024.05          -     -
(uncapped)            2026-03-01  2026-04-30    -        0.00          -     -
$ kohle-cli budget --from 2026-06-10 --to 2026-06-17
account               from        to             cap    spent    over/under  note
--------------------  ----------  ----------  ------  -------  ------------  --------------------
Groceries             2026-06-01  2026-06-30  400.00   230.00       -170.00  partial day 17 of 30
Internet              2026-04-15  2026-07-14   39.90     0.00        -39.90  partial day 64 of 91
Unclassified Expense  2026-06-10  2026-06-17    -        0.00          -     -
(uncapped)            2026-06-10  2026-06-17    -        0.00          -     -
$ kohle-cli budget --to 2026-06-18
Usage: kohle-cli budget [OPTIONS]
Try 'kohle-cli budget --help' for help.

Error: Invalid value for --to: 2026-06-18 is after today
$ kohle-cli budget --from 2026-07-01
Usage: kohle-cli budget [OPTIONS]
Try 'kohle-cli budget --help' for help.

Error: Invalid value for --from: 2026-07-01 is after the last date 2026-06-17
```

The columns are:

- `spent` is net: debits minus credits on the capped account and its subtree
  for lines dated in the period, at the value each line recorded. A refund
  reduces it, so a period can come out negative, as April does. An expense
  split leaves only your own share (see
  [People and splitting](people-and-splitting.md)).
- `over/under` is `spent` minus `cap`, so positive is an overshoot and negative
  an undershoot. There is no `+` sign.
- `note` lists `over` (spent above the cap), `short`, and for the period that
  contains today `partial day N of M`, with today counted. They are joined by
  `, `, and `-` means none.

The two last rows always print, even at 0.00, so spending cannot hide. The
`Unclassified Expense` row is the spending on that account over the whole range,
which is the queue that `list-unclassified` shows. The `(uncapped)` row is the
spending over the whole range on lines whose account had no cap in force, on
itself or on any ancestor, on the line's date. `Unclassified Expense` is left
out of it. Here that is the gym fee, and with no caps at all these two are the
only rows.

There is no rollover: each period stands alone. A line counts toward every
capped ancestor, so a line on a child of a capped parent counts toward the
parent's cap and not toward `(uncapped)`.

`budget` is a pure read. It records no operation and reads no prices.
