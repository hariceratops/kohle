# Multi-currency accounts and FX

## Goal

Hold and report accounts in more than one currency: euro accounts alongside,
for example, Indian stocks that quote in INR, with every report still giving
one comparable total.

The problem behind it: the ledger is multi-unit, but exactly one unit is the
base currency (`BASE_CURRENCY = "EUR"`). Fetched prices are accepted only in
that currency, and the Alpha Vantage plugin reports EUR on every close on the
strength of the user's binding. Binding an INR-quoted symbol today would store
a rupee price as euros, roughly 90 times too high, and the core EUR check
cannot catch it. So holdings in other currencies cannot be priced or valued
until this exists.

## Considerations surfaced

Two different things are bundled here. A currency as a *unit held in an
account* (an INR bank balance) is already expressible: units of kind
`currency`. What is missing is turning a non-base amount into base currency to
value or total it, which needs an exchange rate, and a rate is a price like any
other: dated, fetched, append-only. The price table and plugin contract may
extend to rates rather than needing a parallel mechanism.

The record-vs-compute question settled for securities applies again. A
recorded entry must not depend on a rate fetched later; reports convert at
read time. Cross-currency purchases (paying for INR stocks from a EUR account)
need the rate at the time of the transaction recorded the way a trade price is.

A security quoting in a non-base currency needs both a price and a rate. Which
rate date to use when the two differ, and what "stale" means for a pair, are
undecided.

The importer and price-fetcher specs both put FX out of scope and restate that
a non-base close is a per-unit failure; both would need revisiting.

## Directions rejected

Trusting the symbol binding as the currency assertion for non-EUR instruments.
It is the accepted risk for EUR-only today and does not scale to a portfolio
with Indian holdings.

## Open questions

- Is a rate stored in the existing `prices` table (a currency unit priced in
  the base) or in its own table?
- Which source provides rates, and does it share the price provider question
  (see `eu-price-provider`)?
- How are reports expressed when holdings span currencies: base-currency
  totals only, or also per-currency subtotals?
- Does `record` take a rate for cross-currency entries, or derive one?
- Which instruments (Indian stocks) drive the first version?
