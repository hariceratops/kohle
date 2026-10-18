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
Indian prices, so it stays a source for those. The need is a complement, not a
replacement: a second provider, or closes written by hand into a text file
through the existing file price plugin, for what Alpha Vantage's quota or
coverage cannot reach.

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

A fallback chain across providers (rejected in the price-fetcher spec; each
unit has one binding).

## Open questions

- How many symbols are held, and expected, per exchange? It decides which
  quotas fit.
- Which units go to Alpha Vantage, which to the second source, and which to
  the file plugin?

- Which provider covers Xetra at a quota that fits the real portfolio size?
- Does its response identify a finished daily close, or does the plugin need
  the same strictly-before-today guard as Alpha Vantage?
- Does it quote in EUR for German listings?
- Is a batch endpoint available at all on the free tier?
