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
its price, or the total you stated for it, in the base unit (EUR, see [Accounts and units](accounts-and-units.md)).
This is what lets ten shares at 100 euros balance 1000 euros. An entry paid in
another currency balances in that currency instead, as
[Buying with a currency](#buying-with-a-currency) shows.

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

## Sending money abroad

A remittance takes euros from a euro account and puts a foreign currency into
one of your own accounts. You give the quantity that arrives, in its currency,
and `--total`, the euros that actually left, fees included. kohle works out the
rate from the two, so you never type one:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account IndianBank --type asset
Added account IndianBank (asset) with id 3
$ kohle-cli add-unit INR "Indian rupee" --kind currency
Added unit INR (currency) with id 1
$ kohle-cli record 2026-03-05 "Remittance" 90000 --from Checking --to IndianBank --to-unit INR --total 1000
Recorded 90000 INR for 1000 EUR: credited Checking, debited IndianBank
$ kohle-cli balance IndianBank
unit      quantity  price    price date      market value  status                average cost
------  ----------  -------  ------------  --------------  ------------------  --------------
INR       90000.00  -        -                    1000.00  no price (at cost)            0.01

Market value: 1000.00
1 of 1 holdings estimated (0 stale, 1 at cost)
```

The account now holds 90,000 INR, and that holding costs exactly 1,000.00 euros,
because the cost is the total you stated and not a rounded rate times the
quantity. `average cost` prints at two decimals, so it reads 0.01 here; the
cost behind it is 1000 divided by 90000. Like a purchase of shares, each
remittance is its own lot, and a later one at a different rate keeps its own
cost. The `--total` form needs `--from-unit` or `--to-unit`, cannot be combined
with a price, and both the quantity and the total must be above 0.

Recording reads no fetched rate: the cost comes from the entry alone, so a
rate fetched later never changes it. The currency unit has to exist first, and
is added like any other (see [Accounts and units](accounts-and-units.md#currencies)).

## Opening balances

Holdings you already have when you start enter as an opening entry, not as a
backdated history. It is the remittance form with `--from` an account you name
for the purpose. Make that account an `income` account: the opening then raises
your net worth, whereas an asset account would cancel it out. You state the
quantity and the total euro cost you paid for it, and the lot's cost is that
total. It works the same for a currency and for a security:

```console
$ kohle-cli add-account Opening --type income
Added account Opening (income) with id 2
$ kohle-cli add-account IndianBank --type asset
Added account IndianBank (asset) with id 3
$ kohle-cli add-account Demat --type asset
Added account Demat (asset) with id 4
$ kohle-cli add-unit INR "Indian rupee" --kind currency
Added unit INR (currency) with id 1
$ kohle-cli add-unit INFY "Infosys" --kind security
Added unit INFY (security) with id 2
$ kohle-cli record 2026-01-01 "Opening" 90000 --from Opening --to IndianBank --to-unit INR --total 1000
Recorded 90000 INR for 1000 EUR: credited Opening, debited IndianBank
$ kohle-cli record 2026-01-01 "Opening" 100 --from Opening --to Demat --to-unit INFY --total 1500
Recorded 100 INFY for 1500 EUR: credited Opening, debited Demat
```

The rules are those of [Sending money abroad](#sending-money-abroad): the
quantity and the total must be above 0, and the units must exist first.

## Buying with a currency

A purchase paid in a foreign currency states its price in that currency, with
`--currency`. It takes the euros it cost from the currency's own lots, oldest
first, in the account that pays: the shares cost what the rupees that bought
them cost, and the purchase realises no gain. Take two remittances, then a
purchase of 100 shares at 1,200 rupees each, which is 120,000 rupees:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account IndianBank --type asset
Added account IndianBank (asset) with id 3
$ kohle-cli add-account Demat --type asset
Added account Demat (asset) with id 4
$ kohle-cli add-unit INR "Indian rupee" --kind currency
Added unit INR (currency) with id 1
$ kohle-cli add-unit INFY "Infosys" --kind security
Added unit INFY (security) with id 2
$ kohle-cli record 2026-03-05 "Remittance" 90000 --from Checking --to IndianBank --to-unit INR --total 1000
Recorded 90000 INR for 1000 EUR: credited Checking, debited IndianBank
$ kohle-cli record 2026-03-12 "Remittance" 100000 --from Checking --to IndianBank --to-unit INR --total 1100
Recorded 100000 INR for 1100 EUR: credited Checking, debited IndianBank
$ kohle-cli record 2026-03-20 "Buy INFY" 100 --from IndianBank --to Demat --to-unit INFY --to-price 1200 --currency INR
Recorded 100 INFY @ 1200 INR: credited IndianBank, debited Demat
$ kohle-cli balance Demat
unit      quantity  price    price date      market value  status                average cost
------  ----------  -------  ------------  --------------  ------------------  --------------
INFY        100.00  -        -                    1330.00  no price (at cost)           13.30

Market value: 1330.00
1 of 1 holdings estimated (0 stale, 1 at cost)
$ kohle-cli balance IndianBank
unit      quantity  price    price date      market value  status                average cost
------  ----------  -------  ------------  --------------  ------------------  --------------
INR       70000.00  -        -                     770.00  no price (at cost)            0.01

Market value: 770.00
1 of 1 holdings estimated (0 stale, 1 at cost)
$ kohle-cli realised
No sales

Realised gain: 0.00
```

The purchase used up the first remittance's 90,000 rupees, which cost 1,000
euros, and 30,000 of the second's 100,000, which cost 1,100: 330 euros. The
shares therefore cost 1,330.00 euros, and the 70,000 rupees left are the rest of
the second remittance, 770.00 euros. Nothing is realised, because no rupees
were changed back into euros. You pay with the account's own rupees. A purchase
for more than that account holds still records, since recording reads no lots,
but `balance`, `net-worth`, `positions` and `realised` then fail, naming the
shortfall, until the missing remittance is recorded.

The price, or `--total` for what the whole purchase cost, is in the currency,
and `--currency` takes a currency unit other than EUR. It goes with `--to-unit`
only. Recording still reads no fetched rate: the cost comes from your own earlier
entries.

For a currency, `average cost` in `balance` is the FIFO cost of what is left,
not a moving average, so that the shares and the rupees together still add up to
the euros you sent. Shares in euros keep the moving average, as before. The
price and total you typed for the shares are in rupees, and `entries-in-period`
lists them as typed.

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
