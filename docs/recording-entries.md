# Recording entries

An entry is one event that moves quantities between accounts: an expense, a
transfer, a purchase, a shared bill. Entries are what the whole ledger is made
of; balances and reports are only ways of reading them.

## Why entries balance

kohle is double-entry. Every entry has at least two lines, and each line either
debits an account or credits one. The debits and credits of an entry must
balance, and kohle refuses an entry that does not. That rule is what keeps the
ledger honest: money is never created or lost by a typo, it only moves, so a
missing or doubled amount shows up at once as a refusal rather than weeks later
as a total that is wrong.

On the asset accounts that make up most of a personal ledger, a debit adds to
the account and a credit takes from it. Spending 80 euros on groceries is a
credit to the account the money left and a debit to the one it went to.

Entries balance by value, not by quantity. A line's value is its quantity times
its price, in the base unit (EUR, see [Accounts and units](accounts-and-units.md)).
This is what lets ten shares at 100 euros balance 1000 euros.

## A simple entry

`record` is the two-line case. `--from` is the account that is credited, `--to`
the one that is debited:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Groceries --type asset
Added account Groceries (asset) with id 3
$ kohle-cli record 2026-03-05 "Corner shop" 80 --from Checking --to Groceries
Recorded 80 EUR: credited Checking, debited Groceries
```

The date is `YYYY-MM-DD`, the description is free text, and the quantity is in
euros. The same command records a transfer between your own accounts or an
allocation to an envelope; only the accounts differ. Both accounts must exist
and be leaves, so a wrong name or a parent account is refused:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli record 2026-03-05 "Corner shop" 80 --from Checking --to Groceries
Error: Account 'Groceries' not found
```

## Buying and selling units

An entry in a unit other than euros names the side that carries it, with that
unit and its price. A purchase of ten shares for 100 euros each credits the
cash account with 1000 euros and debits the depot with ten shares:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Broker --type asset
Added account Broker (asset) with id 3
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli record 2026-03-06 "Buy ACME" 10 --from Checking --to Broker --to-unit ACME --to-price 100
Recorded 10 ACME @ 100: credited Checking, debited Broker
$ kohle-cli record 2026-03-07 "Sell ACME" 4 --from Broker --to Checking --from-unit ACME --from-price 110
Recorded 4 ACME @ 110: credited Broker, debited Checking
```

The quantity is now in the unit, 10 shares and then 4, and the price makes the
other side's euros: 1000 for the purchase and 440 for the sale. A unit and its
price go together; one without the other is refused, and so is naming a unit on
both sides. Use `record-split` for anything more involved. The unit has to
exist, so [add it first](accounts-and-units.md#units).

## Entries with more than two lines

`record-split` takes every line in full, as
`ACCOUNT:QUANTITY:UNIT:PRICE:SIDE`, where `SIDE` is `debit` or `credit`. Use it
when an event involves more than two accounts, such as a bill paid by you and
shared with someone else:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Alice --type asset
Added account Alice (asset) with id 3
$ kohle-cli add-account Dining --type asset
Added account Dining (asset) with id 4
$ kohle-cli record-split 2026-03-08 "Shared dinner" --line Checking:120:EUR:1:credit --line Alice:60:EUR:1:debit --line Dining:60:EUR:1:debit
Recorded entry with 3 lines
```

Here you paid 120, Alice owes half and the rest is your own cost. If the sides
do not add up, nothing is recorded:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Dining --type asset
Added account Dining (asset) with id 3
$ kohle-cli record-split 2026-03-08 "Shared dinner" --line Checking:120:EUR:1:credit --line Dining:50:EUR:1:debit
Error: Entry does not balance: debits 50 against credits 120
```

[People and splitting](people-and-splitting.md) shows how to do this with
people under the `People` root, and how to split a line that came from an
imported statement.

### Moving shares between your own depots

To move shares between two of your own depots, credit one and debit the other
in the same entry, with the same price on both:

```console
$ kohle-cli add-account DepotA --type asset
Added account DepotA (asset) with id 2
$ kohle-cli add-account DepotB --type asset
Added account DepotB (asset) with id 3
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli record-split 2026-05-01 "Move to DepotB" --line DepotA:10:ACME:100:credit --line DepotB:10:ACME:100:debit
Recorded entry with 2 lines
```

The realised-profit report treats this as a move, not a sale: the lots keep
their original dates and costs, and any equal price balances the entry. An
entry that moves a different quantity out than in fails that report with
`UnbalancedOwnMove`, so record a sale or purchase as its own entry. See
[Reports](reports.md).

## Reading the ledger

Three commands read what has been recorded. `balance` shows what an account
holds, one row per unit. It rolls up the account's whole subtree, and the last
row of a euro-only account totals the base currency:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Groceries --type asset
Added account Groceries (asset) with id 3
$ kohle-cli record 2026-03-05 "Corner shop" 80 --from Checking --to Groceries
Recorded 80 EUR: credited Checking, debited Groceries
$ kohle-cli balance Checking
unit                     quantity  price    price date      market value  status      average cost
---------------------  ----------  -------  ------------  --------------  --------  --------------
EUR                        -80.00  -        -                     -80.00  -                   1.00
Total (base currency)      -80.00  -        -                     -80.00  -                   -
```

The account is negative because only the spending was recorded, not the
money that arrived. Paying 80 euros out of an account that holds nothing is
allowed.

An account that holds other units gets a row for each. A unit's price, price
date and status come from the closes stored by `fetch-prices`; reports read
those and never fetch one themselves, so an account whose units have no stored
close is valued at cost and says so:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Broker --type asset
Added account Broker (asset) with id 3
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli record 2026-03-06 "Buy ACME" 10 --from Checking --to Broker --to-unit ACME --to-price 100
Recorded 10 ACME @ 100: credited Checking, debited Broker
$ kohle-cli balance Broker
unit      quantity  price    price date      market value  status                average cost
------  ----------  -------  ------------  --------------  ------------------  --------------
ACME         10.00  -        -                    1000.00  no price (at cost)          100.00

Market value: 1000.00
1 of 1 holdings estimated (0 stale, 1 at cost)
```

`average cost` is what was paid per unit, so the market value of 1000.00 here
is the cost. The `Market value` and estimate lines print only when the account
holds a unit other than euros. [Prices](prices.md) explains the stored closes
and the `fresh`, `stale` and `no price` statuses, and `--max-age-days` is in the
[command reference](reference.md).

`entries-in-period` lists the lines that hit an account between two dates. It
shows the counterparty an imported line came from, or `-` for an entry made by
hand:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Groceries --type asset
Added account Groceries (asset) with id 3
$ kohle-cli record 2026-03-05 "Corner shop" 80 --from Checking --to Groceries
Recorded 80 EUR: credited Checking, debited Groceries
$ kohle-cli entries-in-period Groceries 2026-03-01 2026-04-01
  entry_id  date        description    counterparty    side      quantity  unit      value
----------  ----------  -------------  --------------  ------  ----------  ------  -------
         1  2026-03-05  Corner shop    -               dr           80.00  EUR       80.00
```

`side` says whether the line is a debit (`dr`) or a credit (`cr`), and the
`entry_id` is the handle other commands use for that entry.

`list-operations` is the audit trail: one group for each successful change to
the ledger, newest first, naming what was created or changed. The first group
is `init` recording the start Bundesland, and the first entry also creates the
EUR unit. Reading a ledger writes nothing here:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Groceries --type asset
Added account Groceries (asset) with id 3
$ kohle-cli record 2026-03-05 "Corner shop" 80 --from Checking --to Groceries
Recorded 80 EUR: credited Checking, debited Groceries
$ kohle-cli list-operations
  group  entity_type        entity_id  action
-------  ---------------  -----------  --------
      4  units                      1  create
      4  journal_entries            1  create
      3  accounts                   3  create
      2  accounts                   2  create
      1  state_entries              1  create
```

A command that fails exits non-zero and writes its message to stderr, so a
script can test for failure with `kohle-cli ... || handle-failure`, and a
redirect captures results rather than errors.
