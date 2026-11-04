# Prices

A holding in anything but euros is worth its quantity times a price, and the
price changes. kohle keeps the price you paid on every entry, and keeps the
prices you fetch afterwards in a separate history. Reports read that history to
show what a holding is worth now. This page covers how to get prices into it,
how reports use them, and why the two never mix.

Prices come from price plugins, a second kind of plugin in the same
`kohle.plugins` group as the statement importers. Fetching is always an
explicit command: recording, importing and reports never fetch, and a recorded
entry never depends on a price.

## Choosing a price source

`set-price-source UNIT PLUGIN SYMBOL` binds a unit to exactly one plugin and the
symbol that plugin knows it by. Only `security` units can be bound. Running it
again replaces the binding, and the symbol is taken as you give it, never
guessed.

Binding a symbol is also your assertion that it quotes in euros. kohle accepts
only euro closes, and cannot tell that a wrongly bound symbol is really quoted
in another currency.

```console
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli add-unit GOLD-G "Gold, grams" --kind commodity
Added unit GOLD-G (commodity) with id 2
$ kohle-cli set-price-source ACME file ACME
Price source for ACME: file ACME
$ kohle-cli set-price-source ACME file ACME-EUR
Price source for ACME: file ACME-EUR
$ kohle-cli set-price-source GOLD-G file GOLD
Error: Unit 'GOLD-G' is a commodity, not a security
$ kohle-cli set-price-source ACME nosuchplugin ACME
Error: Unknown price plugin 'nosuchplugin'. Available: alphavantage, file
```

Physical gold and other commodity units are not priced yet, so they stay valued
at cost.

## Fetching prices

`fetch-prices` asks each plugin once for the latest daily close of the
securities you hold that are bound to it, and appends it to the price history.
It prints one row per held security. The examples here use the bundled `file`
plugin, which reads a CSV of `identifier,date,close` rows from the file named
by the environment variable `KOHLE_PRICE_FILE`. It works offline, and each
symbol gets its most recent row:

<!-- docs: file prices.csv -->
```csv
identifier,date,close
ACME,2026-03-31,98.40
ACME,2026-05-29,104.20
ACME,2026-06-16,110.50
GLOBEX,2026-03-31,41.10
GLOBEX,2026-05-29,43.75
GLOBEX,2026-06-02,44.30
```

Two securities, bought and bound to that file. Before any source is bound,
`fetch-prices` reports the holdings as `unbound` and changes nothing, which is
not an error. With a source bound but the variable missing, the plugin cannot
run and the holdings are `unpriced`, with the reason:

<!-- docs: uses prices.csv -->
```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Broker --type asset
Added account Broker (asset) with id 3
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli add-unit GLOBEX "Globex Industrial" --kind security
Added unit GLOBEX (security) with id 2
$ kohle-cli record 2026-03-06 "Buy ACME" 10 --from Checking --to Broker --to-unit ACME --to-price 100
Recorded 10 ACME @ 100: credited Checking, debited Broker
$ kohle-cli record 2026-03-07 "Buy GLOBEX" 5 --from Checking --to Broker --to-unit GLOBEX --to-price 40
Recorded 5 GLOBEX @ 40: credited Checking, debited Broker
$ kohle-cli fetch-prices
unit    source    outcome    date    close    detail
------  --------  ---------  ------  -------  --------
ACME    -         unbound    -       -        -
GLOBEX  -         unbound    -       -        -
$ kohle-cli set-price-source ACME file ACME
Price source for ACME: file ACME
$ kohle-cli set-price-source GLOBEX file GLOBEX
Price source for GLOBEX: file GLOBEX
$ kohle-cli fetch-prices
unit    source       outcome    date    close    detail
------  -----------  ---------  ------  -------  ---------------------------
ACME    file:ACME    unpriced   -       -        KOHLE_PRICE_FILE is not set
GLOBEX  file:GLOBEX  unpriced   -       -        KOHLE_PRICE_FILE is not set
Error: 2 held securities unpriced
$ KOHLE_PRICE_FILE=prices.csv kohle-cli fetch-prices
unit    source       outcome    date          close  detail
------  -----------  ---------  ----------  -------  -------------
ACME    file:ACME    priced     2026-06-16    110.5  previous none
GLOBEX  file:GLOBEX  priced     2026-06-02     44.3  previous none
```

The outcomes are:

- `priced`: a new close was stored, with the previous stored close beside it.
- `already stored`: that date already has a close, so nothing changed.
- `unpriced`: the unit is bound but got no price, and the detail says why.
- `unbound`: the unit has no price source.

`fetch-prices` exits non-zero if any bound unit ends unpriced, which is what
makes it usable from a scheduled job. An unbound unit alone is not an error.
There is no fallback to another plugin: to change where a unit's prices come
from, rebind it.

## Appending prices

The price history is append-only and a date is stored once. Running
`fetch-prices` again with nothing new is a no-op, and a later close adds a row
beside the earlier one:

<!-- docs: file prices-later.csv -->
```csv
identifier,date,close
ACME,2026-06-17,112.00
GLOBEX,2026-06-02,44.30
```

<!-- docs: uses prices.csv prices-later.csv -->
```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Broker --type asset
Added account Broker (asset) with id 3
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli add-unit GLOBEX "Globex Industrial" --kind security
Added unit GLOBEX (security) with id 2
$ kohle-cli record 2026-03-06 "Buy ACME" 10 --from Checking --to Broker --to-unit ACME --to-price 100
Recorded 10 ACME @ 100: credited Checking, debited Broker
$ kohle-cli record 2026-03-07 "Buy GLOBEX" 5 --from Checking --to Broker --to-unit GLOBEX --to-price 40
Recorded 5 GLOBEX @ 40: credited Checking, debited Broker
$ kohle-cli set-price-source ACME file ACME
Price source for ACME: file ACME
$ kohle-cli set-price-source GLOBEX file GLOBEX
Price source for GLOBEX: file GLOBEX
$ KOHLE_PRICE_FILE=prices.csv kohle-cli fetch-prices
unit    source       outcome    date          close  detail
------  -----------  ---------  ----------  -------  -------------
ACME    file:ACME    priced     2026-06-16    110.5  previous none
GLOBEX  file:GLOBEX  priced     2026-06-02     44.3  previous none
$ KOHLE_PRICE_FILE=prices.csv kohle-cli fetch-prices
unit    source       outcome         date        close    detail
------  -----------  --------------  ----------  -------  --------
ACME    file:ACME    already stored  2026-06-16  -        -
GLOBEX  file:GLOBEX  already stored  2026-06-02  -        -
$ KOHLE_PRICE_FILE=prices-later.csv kohle-cli fetch-prices
unit    source       outcome         date        close    detail
------  -----------  --------------  ----------  -------  -----------------------------------
ACME    file:ACME    priced          2026-06-17  112.00   previous 110.50000000 on 2026-06-16
GLOBEX  file:GLOBEX  already stored  2026-06-02  -        -
```

`fetch-prices` only ever stores the latest close; it does not backfill earlier
dates. A close that is already stored cannot be corrected in this version.

Every close is checked before it is written: the price must be finite and above
zero, the date not in the future, and the currency EUR. A rejected close leaves
only that symbol's units unpriced, and the other symbols are still stored.

## How reports use prices

`balance`, `net-worth` and `positions` value each holding at the latest stored
close on or before today, and say in the `status` column how much to trust it:

- `fresh`: the latest close is at most 7 days old.
- `stale (YYYY-MM-DD)`: the latest close is older. It is still used, and its
  date is shown so you can judge it.
- `no price (at cost)`: no close is stored, because it was never fetched, no
  source is bound, or the unit has no price. The holding is valued at cost.
- `-`: euros are worth their quantity, so they look up no close.

`--max-age-days N` changes the 7, and `0` means only today's close is fresh.
This guide's sessions run on 2026-06-17. With the closes above, `ACME` was
priced yesterday and `GLOBEX` fifteen days ago. The first `balance` runs before
anything is fetched and values both at cost; the second reads the stored closes;
the third accepts closes up to 30 days old, so both are fresh:

<!-- docs: uses prices.csv -->
```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Broker --type asset
Added account Broker (asset) with id 3
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli add-unit GLOBEX "Globex Industrial" --kind security
Added unit GLOBEX (security) with id 2
$ kohle-cli record 2026-03-06 "Buy ACME" 10 --from Checking --to Broker --to-unit ACME --to-price 100
Recorded 10 ACME @ 100: credited Checking, debited Broker
$ kohle-cli record 2026-03-07 "Buy GLOBEX" 5 --from Checking --to Broker --to-unit GLOBEX --to-price 40
Recorded 5 GLOBEX @ 40: credited Checking, debited Broker
$ kohle-cli balance Broker
unit      quantity  price    price date      market value  status                average cost
------  ----------  -------  ------------  --------------  ------------------  --------------
ACME         10.00  -        -                    1000.00  no price (at cost)          100.00
GLOBEX        5.00  -        -                     200.00  no price (at cost)           40.00

Market value: 1200.00
2 of 2 holdings estimated (0 stale, 2 at cost)
$ kohle-cli set-price-source ACME file ACME
Price source for ACME: file ACME
$ kohle-cli set-price-source GLOBEX file GLOBEX
Price source for GLOBEX: file GLOBEX
$ KOHLE_PRICE_FILE=prices.csv kohle-cli fetch-prices
unit    source       outcome    date          close  detail
------  -----------  ---------  ----------  -------  -------------
ACME    file:ACME    priced     2026-06-16    110.5  previous none
GLOBEX  file:GLOBEX  priced     2026-06-02     44.3  previous none
$ kohle-cli balance Broker
unit      quantity    price  price date      market value  status                average cost
------  ----------  -------  ------------  --------------  ------------------  --------------
ACME         10.00   110.50  2026-06-16           1105.00  fresh                       100.00
GLOBEX        5.00    44.30  2026-06-02            221.50  stale (2026-06-02)           40.00

Market value: 1326.50
1 of 2 holdings estimated (1 stale, 0 at cost)
$ kohle-cli balance Broker --max-age-days 30
unit      quantity    price  price date      market value  status      average cost
------  ----------  -------  ------------  --------------  --------  --------------
ACME         10.00   110.50  2026-06-16           1105.00  fresh             100.00
GLOBEX        5.00    44.30  2026-06-02            221.50  fresh              40.00

Market value: 1326.50
0 of 2 holdings estimated
```

The last line of each report counts the holdings whose market value is an
estimate, meaning those that are stale or valued at cost. A stale close is
still a real price, so a stale holding is usually a better value than the cost
but a worse one than a fresh close. Fetch again to refresh it.

## Why reports never call a price plugin

A report only reads the prices already stored. It never asks a plugin for a
fresh one, for three reasons.

- **Reports stay fast and work offline.** A price source is a network call
  with a key and a rate limit. If `balance` made one, a train without signal
  would turn a read into an error.
- **A report gives the same answer twice.** The history only changes when you
  run `fetch-prices`, so two `net-worth` runs a minute apart agree, and the
  `status` column tells you how old the numbers are instead of hiding it.
- **Recording never depends on a price.** An entry carries the price you gave
  it and nothing else, so what you recorded cannot change because a source said
  something different on some day. Only the valuation of a holding in a report
  reads the history, and it never writes to the ledger.

The cost of this is that a price is only as fresh as your last `fetch-prices`.
The `stale` and `no price (at cost)` statuses say so when that matters, and
running `fetch-prices` on a schedule (see
[Several devices](several-devices.md)) keeps them rare.

## The bundled price plugins

- **`file`** reads `identifier,date,close` rows from the CSV named by
  `KOHLE_PRICE_FILE` and returns each symbol's most recent row, as above. It is
  the way to price a unit no other plugin covers, and the one to use when you
  want to type prices yourself or keep them in a spreadsheet export.
- **`alphavantage`** reads Alpha Vantage's `TIME_SERIES_DAILY`, with the API key
  in `KOHLE_ALPHAVANTAGE_KEY`. It stores the latest daily bar dated before today
  (UTC), so a trading day still in progress is never stored. The free tier
  allows one symbol per request and about 25 requests a day. Symbols are
  requested with the oldest stored close first, so prices rotate, and a
  throttled run keeps what it fetched and reports the rest as `transient`.
  Symbols carry the exchange suffix (for example `.DEX`), so look up the euro
  listing yourself.

<!-- docs: illustration -->
```sh
export KOHLE_ALPHAVANTAGE_KEY=your-key
kohle-cli set-price-source ACME alphavantage ACME.DEX
kohle-cli fetch-prices
```

That fetch needs the network and a key, so this guide does not run it. The
[plugin list](plugins.md) shows what is installed, and
[Writing plugins](writing-plugins.md) explains how to add a price source of
your own.
