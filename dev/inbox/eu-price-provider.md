# A price provider with good European coverage

## Goal

Find and add a free, safe price source whose coverage fits a German portfolio
(Xetra ETFs and stocks) without exhausting its quota, as a second price plugin.

The problem behind it: the first real plugin, Alpha Vantage, works for Xetra
(`EUNL.DE` and `CCC3.DE` priced in a smoke test) but allows about 25 requests a
day with one symbol per request. A portfolio past 25 symbols cannot be
refreshed in one run, which bounds worst-case staleness at roughly
ceil(symbols / 25) days plus weekends, and symbols the provider does not carry
cost a request every run.

## Considerations surfaced

**Indian closes are in scope too.** `multi-currency-and-fx` settled that
Indian stocks are held now. Per the user, Alpha Vantage already provides
Indian prices, but at one symbol per call. The need is a complement, not a
replacement: a second provider, or closes written by hand into a text file
through the existing file price plugin, for what Alpha Vantage's quota or
coverage cannot reach.

**Indian closes: the NSE bhavcopy (chosen direction).** NSE publishes one
end-of-day file per trading day with the official close of every listed
security, at
`https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`
(the UDiFF format NSE switched to in July 2024). Pulled successfully on
2026-10-18 for 2026-10-16: a 206 KB zip, 3,675 rows, e.g. `INFY`
`INE009A01021` `EQ` close 1161.20.

- *One download prices every Indian holding*, whatever their number. Indian
  symbols leave the Alpha Vantage quota entirely, and its 25 daily calls go to
  Xetra.
- *Bind by ISIN.* Every row carries the ISIN (`ISIN` column); kohle units are
  already identified by ISIN, so the binding symbol can be the ISIN itself,
  sturdier than a ticker that NSE renames.
- *Filter on the series.* Rows mix series (`SctySrs`); matching takes the `EQ`
  row for the ISIN so another listing of the same ISIN is not picked up.
- *It is a finished close.* `TradDt` names the trading day and `ClsPric` is
  the official close, so no strictly-before-today guard is needed. The plugin
  tries the latest weekday and steps back over holidays until a file exists.
- *Quote currency is INR*, which needs `multi-currency-and-fx` before these
  closes can be stored.
- *Browser-like headers are required.* The request succeeded with a browser
  `User-Agent` and `Referer: https://www.nseindia.com/`; with curl's defaults
  it failed with an HTTP/2 stream error. NSE changes URLs and formats from
  time to time (the 2024 UDiFF switch), so the plugin must fail loudly per
  unit when the file or its columns are not what it expects.
- *Terms not found.* NSE's terms on automated download were not located, and
  the site states no rate limit or uptime commitment.

Alternatives checked for India (October 2026, from secondary sources that
partly disagree): Groww's trade API is paid (₹499 + tax a month; the free
trial excludes quotes and historical candles) and ties kohle to the broker;
ICICI Breeze is free but for ICICIdirect customers only; Twelve Data, EODHD
and Finnhub free tiers appear US-focused or too small. BSE's bhavcopy was not
examined.

**No single provider is required.** Each unit has its own price binding, so
Xetra symbols, Indian symbols and the INR/EUR rate can come from different
sources side by side. A free reference-rate source (the ECB publishes daily
EUR rates) is a candidate for the rate, unverified for terms and fit.

"Free and safe" is taken to mean: an official API key (not scraping), terms
that allow personal use, a documented rate limit, and a response from which a
finished daily close can be identified.

Candidates noted but none confirmed for German listings: Twelve Data (reported
at 800 requests a day, but the user believes it lacks European data),
Finnhub, EODHD (lists Xetra tickers, paid from about $19.99), Stooq (keyless
CSV, coverage and terms unchecked), Marketstack (100 requests a month, too
small). Unofficial Yahoo access is rejected as unsafe.

Adding a provider needs no core change: a new file under `kohle/app/plugins/`
registered under `kohle.plugins`, then units rebound with `set-price-source`.
The plugin contract returns one close per symbol and does not require one
request per symbol, so a provider with a batch endpoint fits it.

## Directions rejected

- **A fallback chain across providers**: rejected in the price-fetcher spec;
  each unit has one binding.
- **Groww's API for Indian closes**: paid, and broker-bound, for data the
  exchange publishes free.
- **Alpha Vantage for Indian closes**: possible, but spends the 25 daily calls
  one symbol at a time on what bhavcopy prices in one download.

## Open questions

- How many symbols are held, and expected, per exchange? It decides which
  quotas fit.
- Which units go to Alpha Vantage, which to the second source, and which to
  the file plugin?
- Does bhavcopy count as "safe" under the definition above? It is the
  exchange's own published file, not scraped pages, but it is not an API with
  a key and needs browser-like headers to download.
- Is BSE's bhavcopy needed for anything not listed on NSE?
- Which provider covers Xetra at a quota that fits the real portfolio size?
- Does its response identify a finished daily close, or does the plugin need
  the same strictly-before-today guard as Alpha Vantage?
- Does it quote in EUR for German listings?
- Is a batch endpoint available at all on the free tier?
