# Reports

Balances, net worth, positions and realised gains.

The reports read the ledger and the stored price history, and never write to
either. They are the commands you run to ask where you stand: `net-worth` for
the total, `positions` and `realised` for securities, and `net-worth-history`
for the total at past dates. `balance`, which shows one account, is on
[Recording entries](recording-entries.md). Every column of every report is
listed in the [command reference](reference.md), so this page shows the output
and explains what is worth knowing about it.

The examples share one small ledger, built from two files shipped with these
docs. `broker.csv` is a fictional broker export read by the `kohle-simple-broker`
importer, and `prices.csv` holds closes for the same two securities, `ACME` and
`GLOBEX`. It buys 10 `ACME` at 100 and 5 more at 104, buys 5 `GLOBEX` at 40,
sells 12 `ACME` at 112 on 20 April, and pays a 3.50 `GLOBEX` dividend. Today is
17 June 2026 throughout. `Checking` is negative because the sample records no
deposit, which does not matter for the reports.

## Net worth

`net-worth` totals your own accounts and what people owe you, valued in euros.
Each holding is shown twice: at cost, which is what you recorded, and at
market, which is the quantity times the latest stored close. The close comes
from the price history that `fetch-prices` fills, and reports never fetch (see
[Prices](prices.md)).

Here the ledger also lends 16 euros to Jonas, who lives under the `People`
branch:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Broker --type asset
Added account Broker (asset) with id 3
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli add-unit GLOBEX "Globex Industrial" --kind security
Added unit GLOBEX (security) with id 2
$ kohle-cli import-statement kohle-simple-broker Checking Broker broker.csv
Import succeeded, 5 entries imported
$ kohle-cli add-account Jonas --type asset --parent People
Added account Jonas (asset) with id 6
$ kohle-cli record 2026-05-20 "Lent to Jonas" 16 --from Checking --to Jonas
Recorded 16 EUR: credited Checking, debited Jonas
$ kohle-cli set-price-source ACME file ACME
Price source for ACME: file ACME
$ kohle-cli set-price-source GLOBEX file GLOBEX
Price source for GLOBEX: file GLOBEX
$ KOHLE_PRICE_FILE=prices.csv kohle-cli fetch-prices
unit    source       outcome    date          close  detail
------  -----------  ---------  ----------  -------  -------------
ACME    file:ACME    priced     2026-06-16    110.5  previous none
GLOBEX  file:GLOBEX  priced     2026-06-02     44.3  previous none
$ kohle-cli net-worth
section               unit      quantity    price  price date      market value  status                at cost
--------------------  ------  ----------  -------  ------------  --------------  ------------------  ---------
Own accounts          ACME          3.00   110.50  2026-06-16            331.50  fresh                  304.00
Own accounts          EUR        -388.50     -     -                    -388.50  -                     -388.50
Own accounts          GLOBEX        5.00    44.30  2026-06-02            221.50  stale (2026-06-02)     200.00
Receivables (People)  EUR          16.00     -     -                      16.00  -                       16.00

Net worth (at cost): 131.50
Net worth (at market): 180.50
1 of 2 holdings estimated (1 stale, 0 at cost)
```

Income and expense accounts are left out, because every entry balances and
including them would always report exactly 0. The `People` branch appears as its
own section, `Receivables (People)`, at face value. A person who is owed money
by you has a negative balance and lowers the total, and one who owes you raises
it. Per-person balances are `balance <person>` or `who-owes-what`, which
[People and splitting](people-and-splitting.md) covers.

The `status` column says where each market value came from. The values, the
`--max-age-days` option that moves the freshness limit, and the last line that
counts estimated holdings are explained on [Prices](prices.md#how-reports-use-prices).
`Net worth (at cost)` totals the `at cost` column, and `Net worth (at market)`
totals the `market value` column across both sections. The estimates line
counts the holdings that are not euros and not zero, so `GLOBEX`, whose close is
fifteen days old, is the one estimate above.

### Holdings quoted in another currency

A stock can be quoted in a currency other than euros, for example a share
bound with a quote currency of `INR`. `balance`, `net-worth` and `positions`
then value it as quantity times its latest close times the latest rate of that
currency, and rupees you hold as cash are valued as quantity times the rate.
The close and the rate are each the latest stored on or before the report's
date, and their dates need not match.

- `price` and `price date` show the close in its own currency.
- `status` is the worse of the two: a stale close or a stale rate makes the row
  stale, and the date shown is the older of the two.
- If the close or the rate is missing, the holding is valued at its cost in
  euros and reads `no price (at cost)`.

The rate is an ordinary price of the currency unit, fetched like any other (see
[Prices](prices.md)).

When any close in a table is quoted in another currency, `balance`, `net-worth`
and `positions` add a `quoted in` column after `price` that names the currency of
each price. A currency's own price, such as the rate of the rupee, is shown to
eight places. A table with only euro prices is unchanged.

`positions` shows `price` in that quote currency, while `market value`, `FIFO
cost` and `unrealised gain` are always in euros. Rupees you hold are a row of
their own: their FIFO cost is the euros you sent, so their unrealised gain is
the unrealised exchange-rate gain. A share quoted in rupees has the same gain
folded in with its price gain, since both are measured in euros.

### Subtotals per currency

When some holding is in a currency other than euros, `net-worth` and
`positions` print a small table after their closing lines, with one row per
currency: `market value` in that currency and `in EUR`.

- A holding's currency is the unit itself for a currency unit such as `INR`,
  its binding's quote currency for a security bound with one, and euros for a
  security with no binding.
- The `in EUR` figures add up to the euro total, which is unchanged.
- `market value` shows `-` when any holding in that currency has no close in
  it, for example while a rebound security still has only euro closes. A
  security valued at cost has no close, so it counts as missing.
- Euro cash is its own quantity, so the `EUR` row shows `-` only when a euro
  security has no euro close.

A ledger with only euro holdings prints no subtotal table. `balance` and
`net-worth-history` print none either.

## Positions and profit

`positions` lists each security still held, summed over all your own accounts,
at its latest stored close beside the cost of the lots still held. `realised`
lists every sale with its gain. Both replay the ledger in order and charge each
sale against the oldest lots first, which is first in, first out (FIFO), per
depot. Lots are rebuilt on every run and never stored.

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Broker --type asset
Added account Broker (asset) with id 3
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli add-unit GLOBEX "Globex Industrial" --kind security
Added unit GLOBEX (security) with id 2
$ kohle-cli import-statement kohle-simple-broker Checking Broker broker.csv
Import succeeded, 5 entries imported
$ kohle-cli set-price-source ACME file ACME
Price source for ACME: file ACME
$ kohle-cli set-price-source GLOBEX file GLOBEX
Price source for GLOBEX: file GLOBEX
$ KOHLE_PRICE_FILE=prices.csv kohle-cli fetch-prices
unit    source       outcome    date          close  detail
------  -----------  ---------  ----------  -------  -------------
ACME    file:ACME    priced     2026-06-16    110.5  previous none
GLOBEX  file:GLOBEX  priced     2026-06-02     44.3  previous none
$ kohle-cli realised
date        account    unit      quantity    proceeds    FIFO cost    gain
----------  ---------  ------  ----------  ----------  -----------  ------
2026-04-20  Broker     ACME         12.00     1344.00      1208.00  136.00

Realised gain: 136.00
$ kohle-cli realised --year 2025
No sales

Realised gain: 0.00
$ kohle-cli balance Broker
unit      quantity    price  price date      market value  status                average cost
------  ----------  -------  ------------  --------------  ------------------  --------------
ACME          3.00   110.50  2026-06-16            331.50  fresh                       101.33
GLOBEX        5.00    44.30  2026-06-02            221.50  stale (2026-06-02)           40.00

Market value: 553.00
1 of 2 holdings estimated (1 stale, 0 at cost)
$ kohle-cli positions
unit      quantity    price  price date      market value  status                FIFO cost    unrealised gain
------  ----------  -------  ------------  --------------  ------------------  -----------  -----------------
ACME          3.00   110.50  2026-06-16            331.50  fresh                    312.00              19.50
GLOBEX        5.00    44.30  2026-06-02            221.50  stale (2026-06-02)       200.00              21.50

Market value: 553.00
FIFO cost: 512.00
Unrealised gain: 41.00
1 of 2 holdings estimated (1 stale, 0 at cost)
```

The sale of 12 `ACME` used the whole first lot, 10 at 100, and 2 of the second,
at 104, for a cost of 1208 against proceeds of 1344. That leaves 3 `ACME`, all
from the second lot, so `positions` reports a FIFO cost of 312.

`balance`, by contrast, shows a moving average cost, 101.33 per share for the
same 3 `ACME`, so the two can disagree about what a lot cost. `positions` and
`realised` are the ones to compare with a broker's certificate.

- Proceeds are the quantity sold times the sale line's recorded unit price. The
  figures are gross, before fees and tax, so `realised` is a cross-check and not
  a tax computation.
- `--year` lists only sales dated in that year. Their gains still use lots bought
  in earlier years. Without it every sale from every year is listed under one
  total.
- `unrealised gain` is `market value` minus `FIFO cost`. A security with no
  stored close is valued at its FIFO cost, so its gain is 0 and the row reads
  `no price (at cost)`.
- With nothing sold or held, `No sales` or `No positions` takes the place of
  the table.
- The `People` branch is excluded from both reports. `positions` never fetches
  prices.

### Exchange-rate gain

Rupees are lots like shares. Buying shares or spending rupees realises nothing;
the gain is realised when rupees are changed back into euros (see
[Changing a currency back into euros](recording-entries.md#changing-a-currency-back-into-euros)).
`realised` then lists a row with the unit `INR`: the proceeds are the euros
received, the FIFO cost is the euros the rupees used up cost, and the gain is
the difference. It counts under the same `Realised gain` total as share sales,
and `--year` filters it the same way. A shortfall of rupees fails `realised`
and `positions` as a whole.

### Economic gain, not tax basis

The euro gain kohle reports is the economic gain: what you ended up with in
euros against what you actually sent. Cost is the euros actually sent, the
`--total` of the remittance, carried through the rupee lots to the shares they
bought. Proceeds use the rate recorded on the entry that received the rupees.
No report reads a fetched rate for a gain, so a rate fetched later never
changes it.

This is not the basis German tax law converts on. As far as the author
understands it (unverified), that basis uses the exchange rate on the purchase
date and on the sale date, and treats the currency itself as a separate private
sale. No German broker certificate exists for these holdings, so there is
nothing to check kohle's figure against. Do not read it as a tax figure.

Take a remittance of 90,000 rupees for 1,000 euros, a purchase of 50 shares at
1,200 rupees paid from those rupees, and a sale of the 50 shares at 1,300 rupees
with a recorded rate of 0.0104 euros per rupee:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account IndianBank --type asset
Added account IndianBank (asset) with id 3
$ kohle-cli add-account Demat --type asset
Added account Demat (asset) with id 4
$ kohle-cli add-account DematCash --type asset
Added account DematCash (asset) with id 5
$ kohle-cli add-unit INR "Indian rupee" --kind currency
Added unit INR (currency) with id 1
$ kohle-cli add-unit INFY "Infosys" --kind security
Added unit INFY (security) with id 2
$ kohle-cli record 2026-03-05 "Remittance" 90000 --from Checking --to IndianBank --to-unit INR --total 1000
Recorded 90000 INR for 1000 EUR: credited Checking, debited IndianBank
$ kohle-cli record 2026-03-20 "Buy INFY" 50 --from IndianBank --to Demat --to-unit INFY --to-price 1200 --currency INR
Recorded 50 INFY @ 1200 INR: credited IndianBank, debited Demat
$ kohle-cli record 2026-05-10 "Sell INFY" 50 --from Demat --to DematCash --from-unit INFY --from-price 1300 --currency INR --rate 0.0104
Recorded 50 INFY @ 1300 INR at 0.0104 EUR: credited Demat, debited DematCash
$ kohle-cli realised
date        account    unit      quantity    proceeds    FIFO cost    gain
----------  ---------  ------  ----------  ----------  -----------  ------
2026-05-10  Demat      INFY         50.00      676.00       666.67    9.33

Realised gain: 9.33
```

The 60,000 rupees spent on the shares cost 1000 × 60000 / 90000 = 666.67 euros
of the euros sent, so that is the shares' FIFO cost. The sale brought in 65,000
rupees, which the entry values at 65000 × 0.0104 = 676.00 euros, so the gain is
676.00 - 666.67 = 9.33. It folds the price gain and the exchange-rate gain
together. A tax computation would instead convert the purchase at the rate on
the purchase date, which kohle never looks up, and the sale at the rate on the
sale date, which here is whatever you recorded.

### FIFO across your own depots

A security can sit in more than one depot of your own. Lots are tracked per
depot, and moving shares from one to another is a move, not a sale. Record it
as one entry that credits one depot and debits the other with the same quantity.
The lots keep their original dates and costs, and the price on the move's lines
is ignored. Selling from the second depot afterwards therefore charges the
cost of the lot you bought, not the price of the move:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Broker --type asset
Added account Broker (asset) with id 3
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli add-unit GLOBEX "Globex Industrial" --kind security
Added unit GLOBEX (security) with id 2
$ kohle-cli import-statement kohle-simple-broker Checking Broker broker.csv
Import succeeded, 5 entries imported
$ kohle-cli add-account Depot2 --type asset
Added account Depot2 (asset) with id 6
$ kohle-cli set-price-source ACME file ACME
Price source for ACME: file ACME
$ kohle-cli set-price-source GLOBEX file GLOBEX
Price source for GLOBEX: file GLOBEX
$ KOHLE_PRICE_FILE=prices.csv kohle-cli fetch-prices
unit    source       outcome    date          close  detail
------  -----------  ---------  ----------  -------  -------------
ACME    file:ACME    priced     2026-06-16    110.5  previous none
GLOBEX  file:GLOBEX  priced     2026-06-02     44.3  previous none
$ kohle-cli record-split 2026-05-01 "Move to Depot2" --line Broker:3:ACME:110:credit --line Depot2:3:ACME:110:debit
Recorded entry with 2 lines
$ kohle-cli record 2026-06-10 "Sell ACME" 1 --from Depot2 --to Checking --from-unit ACME --from-price 120
Recorded 1 ACME @ 120: credited Depot2, debited Checking
$ kohle-cli realised
date        account    unit      quantity    proceeds    FIFO cost    gain
----------  ---------  ------  ----------  ----------  -----------  ------
2026-04-20  Broker     ACME         12.00     1344.00      1208.00  136.00
2026-06-10  Depot2     ACME          1.00      120.00       104.00   16.00

Realised gain: 152.00
$ kohle-cli positions
unit      quantity    price  price date      market value  status                FIFO cost    unrealised gain
------  ----------  -------  ------------  --------------  ------------------  -----------  -----------------
ACME          2.00   110.50  2026-06-16            221.00  fresh                    208.00              13.00
GLOBEX        5.00    44.30  2026-06-02            221.50  stale (2026-06-02)       200.00              21.50

Market value: 442.50
FIFO cost: 408.00
Unrealised gain: 34.50
1 of 2 holdings estimated (1 stale, 0 at cost)
$ kohle-cli balance Depot2
unit      quantity    price  price date      market value  status      average cost
------  ----------  -------  ------------  --------------  --------  --------------
ACME          2.00   110.50  2026-06-16            221.00  fresh             110.00

Market value: 221.00
0 of 1 holdings estimated
$ kohle-cli record-split 2026-06-11 "Odd move" --line Depot2:2:ACME:165:credit --line Broker:3:ACME:110:debit
Recorded entry with 2 lines
$ kohle-cli realised
Error: Entry 8 on 2026-06-11 moves 2 ACME out of own accounts but 3 in; record the move and any sale or purchase as separate entries
```

After the move, the 3 `ACME` left from the second lot sit in `Depot2`, and the
sale of one of them at 120 realises 16 against the original cost of 104. `balance Depot2`
shows 110, the price of the move, as its average cost, because `balance` only
sees the lines in that account. `positions` still holds the lots at 104.

A move must move the same quantity out as in. An entry that balances in euros
but moves 2 shares out and 3 in is not a move and not a trade either, so
`realised` and `positions` refuse to run until it is fixed, and name the entry.
Record a sale or a purchase as its own entry instead of folding it into a move.
The same two reports also fail, printing nothing else, when a sale exceeds the
lots its depot holds (the error names the unit, depot, date and shortfall), or
when a security moves between one of your accounts and a `People` account, which
is not supported yet.

## Net worth over time

`net-worth-history` shows net worth at past sample dates, chosen by the ledger's
sampling rules, plus a final row dated `--to` when that is not itself a sample
date. A fresh ledger samples the 15th, role `mid-month`, and the last working
day, role `salary`, of each month. Pass `--from` and `--to` to get the same rows
whenever you run it:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Broker --type asset
Added account Broker (asset) with id 3
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli add-unit GLOBEX "Globex Industrial" --kind security
Added unit GLOBEX (security) with id 2
$ kohle-cli import-statement kohle-simple-broker Checking Broker broker.csv
Import succeeded, 5 entries imported
$ kohle-cli set-price-source ACME file ACME
Price source for ACME: file ACME
$ kohle-cli set-price-source GLOBEX file GLOBEX
Price source for GLOBEX: file GLOBEX
$ KOHLE_PRICE_FILE=prices.csv kohle-cli fetch-prices
unit    source       outcome    date          close  detail
------  -----------  ---------  ----------  -------  -------------
ACME    file:ACME    priced     2026-06-16    110.5  previous none
GLOBEX  file:GLOBEX  priced     2026-06-02     44.3  previous none
$ kohle-cli net-worth-history --from 2026-03-01 --to 2026-06-17
date          at cost    at market  estimated    role
----------  ---------  -----------  -----------  ---------
2026-03-15       0.00         0.00  2 of 2       mid-month
2026-03-31       0.00         0.00  2 of 2       salary
2026-04-15       0.00         0.00  2 of 2       mid-month
2026-04-30     128.00       128.00  2 of 2       salary
2026-05-15     131.50       131.50  2 of 2       mid-month
2026-05-29     131.50       131.50  2 of 2       salary
2026-06-15     131.50       153.00  2 of 2       mid-month
2026-06-17     131.50       180.50  1 of 2       -
$ kohle-cli net-worth-history --from 2026-03-01 --to 2026-06-17 --role salary
date          at cost    at market  estimated    role
----------  ---------  -----------  -----------  ------
2026-03-31       0.00         0.00  2 of 2       salary
2026-04-30     128.00       128.00  2 of 2       salary
2026-05-29     131.50       131.50  2 of 2       salary
2026-06-17     131.50       180.50  1 of 2       -
$ kohle-cli net-worth-history --from 2026-06-10 --to 2026-06-01
Usage: kohle-cli net-worth-history [OPTIONS]
Try 'kohle-cli net-worth-history --help' for help.

Error: Invalid value for --from: 2026-06-10 is after the last date 2026-06-01
$ kohle-cli net-worth-history --to 2026-06-18
Usage: kohle-cli net-worth-history [OPTIONS]
Try 'kohle-cli net-worth-history --help' for help.

Error: Invalid value for --to: 2026-06-18 is after today
```

Each row values the ledger as `net-worth` does, using only the lines dated on or
before that date. A non-euro holding is valued at its last stored close on or
before that date, never a later one, and a date before any stored close values
the holding at cost. Both count in the `estimated` column, which reads `K of M`
like the last line of `net-worth`.

A holding quoted in another currency is valued the same way at each date: its
latest close on or before the date times the latest rate of that currency on or
before the same date, and rupees held as cash at the rate alone. A date with no
close or no rate for a holding values it at cost and counts it in `estimated`,
as `net-worth` does. Closes and rates need not share a date.

That is why the history is flat at cost while the market column moves: buying
shares swaps cash for shares at the same value, and the market column only moves
once there is a close to value them at. `fetch-prices` stores only the latest
close and does not backfill, so the history shows market movement only from the
closes you have fetched: from 2 June for `GLOBEX` and from 16 June for `ACME`,
and every earlier row is valued at cost. The
report never fetches prices or calls a price plugin.

The `role` column lists every role whose rule reached the date, so a date hit by
two rules is one row, such as `mid-month, salary`. The `--to` row, when it is
not a sample date, has role `-`. `--role` keeps only the rows listing that role,
and the `--to` row is always shown.

`--from` defaults to the earliest ledger entry and `--to` to today. A `--to`
after today, or a `--from` later than `--to`, is a usage error. With `--to`
omitted the last row equals what `net-worth` prints, unless an entry is dated in
the future, which `net-worth` counts and the history does not.

### Sampling rules

The rule list is stored in the ledger and applies to its whole history.
`set-sampling-rules` replaces it as a whole, so changing it re-samples every
past month. `list-sampling-rules` prints it. The default is
`mid-month: day 15; salary: last workday`:

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Broker --type asset
Added account Broker (asset) with id 3
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli add-unit GLOBEX "Globex Industrial" --kind security
Added unit GLOBEX (security) with id 2
$ kohle-cli import-statement kohle-simple-broker Checking Broker broker.csv
Import succeeded, 5 entries imported
$ kohle-cli set-price-source ACME file ACME
Price source for ACME: file ACME
$ kohle-cli set-price-source GLOBEX file GLOBEX
Price source for GLOBEX: file GLOBEX
$ KOHLE_PRICE_FILE=prices.csv kohle-cli fetch-prices
unit    source       outcome    date          close  detail
------  -----------  ---------  ----------  -------  -------------
ACME    file:ACME    priced     2026-06-16    110.5  previous none
GLOBEX  file:GLOBEX  priced     2026-06-02     44.3  previous none
$ kohle-cli list-sampling-rules
mid-month: day 15; salary: last workday
$ kohle-cli set-sampling-rules "mid-month: day 15; salary: 3rd fri"
Set sampling rules to mid-month: day 15; salary: 3rd fri
$ kohle-cli list-sampling-rules
mid-month: day 15; salary: 3rd fri
$ kohle-cli net-worth-history --from 2026-03-01 --to 2026-06-17
date          at cost    at market  estimated    role
----------  ---------  -----------  -----------  -----------------
2026-03-15       0.00         0.00  2 of 2       mid-month
2026-03-20       0.00         0.00  2 of 2       salary
2026-04-15       0.00         0.00  2 of 2       mid-month
2026-04-17       0.00         0.00  2 of 2       salary
2026-05-15     131.50       131.50  2 of 2       mid-month, salary
2026-06-15     131.50       153.00  2 of 2       mid-month
2026-06-17     131.50       180.50  1 of 2       -
$ kohle-cli set-sampling-rules "mid-month: day 15; salary: every 3 years from 2026-01-15"
Error: invalid rule 'every 3 years from 2026-01-15'; expected a unit days, weeks or months; for years write months, e.g. every 24 months
$ kohle-cli set-sampling-rules "bogus: day 3"
Error: unknown role 'bogus' in 'bogus: day 3'; roles: mid-month, salary
```

A list is `"<role>: <rule>; <role>: <rule>"`, and the two roles are fixed:
`mid-month` and `salary`. The rule `3rd fri` samples the third Friday of the
month, and on 15 May 2026, a Friday, it lands on the same day as `day 15`, so
that date is one row. An invalid rule or role writes nothing, and the error
names the bad part and what is allowed. The rules are:

| Rule | Meaning |
|---|---|
| `day N` | Calendar day N (1-31). Never moves. In a shorter month it is the last day. |
| `workday N` | Day N, clamped the same way, or the last working day before it. |
| `<nth> <weekday>` | `1st` to `4th` plus `mon` to `sun`, such as `3rd fri`: that weekday of the month, or the working day before it if it is not one. |
| `last workday` | The last working day of the month. |
| `last day` | The last calendar day of the month. |
| `every N days\|weeks\|months from YYYY-MM-DD` | Every N units in step with the date, which fixes only the phase, so it also lands before the date. N is 1 to 999 and the units are plural, with no `years`: write `every 24 months`. A month-based date keeps the start's day, clamped to each month without drifting. Never moves to a working day. |
| `yearly MM-DD` | That calendar day every year. `yearly 02-29` lands on 28 February in non-leap years. Never moves to a working day. |

A working day is Monday to Friday, not a public holiday of the Bundesland in
force on the rule's unshifted date, and never 24 or 31 December. A shift only
moves backward, and may land in the previous month. The row is dated where it
lands and includes its lines. `day 15` on a Sunday stays on the 15th, while
`workday 15` moves to the Friday before. With the default list, a month ending
on a Saturday or a holiday samples the working day before it.

### Bundesland history

Which days are holidays depends on the Bundesland, which is an effective-dated
history. Moving applies from a date onward and leaves earlier samples alone.
`workday 4` shows it. Fronleichnam, 4 June 2026, is a holiday in Baden-Wuerttemberg
and not in Niedersachsen, so the sample for June moves to the day before while
the ledger is in `BW`, and stays put after a move to `NI`. The 4th of April is a Saturday and the Friday before it is
Good Friday, so that sample lands on Thursday 2 April in both. The ledger here is empty, so the values are zero:

```console
$ kohle-cli set-sampling-rules "salary: workday 4"
Set sampling rules to salary: workday 4
$ kohle-cli list-states
from    state
------  -------
start   BW
$ kohle-cli net-worth-history --from 2026-03-01 --to 2026-06-17 --role salary
date          at cost    at market  estimated    role
----------  ---------  -----------  -----------  ------
2026-03-04       0.00         0.00  0 of 0       salary
2026-04-02       0.00         0.00  0 of 0       salary
2026-05-04       0.00         0.00  0 of 0       salary
2026-06-03       0.00         0.00  0 of 0       salary
2026-06-17       0.00         0.00  0 of 0       -
$ kohle-cli move-state --from 2026-06-01 NI
Set state from 2026-06-01 to NI
$ kohle-cli list-states
from        state
----------  -------
start       BW
2026-06-01  NI
$ kohle-cli net-worth-history --from 2026-03-01 --to 2026-06-17 --role salary
date          at cost    at market  estimated    role
----------  ---------  -----------  -----------  ------
2026-03-04       0.00         0.00  0 of 0       salary
2026-04-02       0.00         0.00  0 of 0       salary
2026-05-04       0.00         0.00  0 of 0       salary
2026-06-04       0.00         0.00  0 of 0       salary
2026-06-17       0.00         0.00  0 of 0       -
$ kohle-cli move-state --from 2026-06-01 XX
Error: invalid state 'XX'; expected one of BB, BE, BW, BY, HB, HE, HH, MV, NI, NW, RP, SH, SL, SN, ST, TH
$ kohle-cli list-operations
  group  entity_type            entity_id  action
-------  -------------------  -----------  --------
      3  state_entries                  2  create
      2  sampling_rule_lists            2  create
      1  state_entries                  1  create
```

`--from` is required and takes a date or `start`, the entry that applies from
the start of the ledger. The date may be in the future. Repeating a date
replaces that entry, which is how you correct a mistake, and a later entry wins
from its own date onward. `list-states` shows the history oldest first, with
`start` for the first entry. An invalid code writes nothing and lists the valid
ones. Each successful change is one operation in `list-operations`. A ledger
with no `start` entry makes `net-worth-history` exit with an error that points
to `move-state --from start <code>`.

Holidays come from the pinned `holidays` package, so a deliberate upgrade of it
can move a date.
