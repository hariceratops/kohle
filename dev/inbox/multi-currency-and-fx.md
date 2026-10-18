# Multi-currency accounts and FX

## Goal

Hold and report accounts in more than one currency: euro accounts alongside
an Indian bank account and Indian stocks held in an Indian demat account, with
every report still giving one comparable total in euros, and gains that
reflect what was actually paid in euros.

The problem behind it: the ledger is multi-unit, but exactly one unit is the
base currency (`BASE_CURRENCY = "EUR"`). Fetched prices are accepted only in
that currency, and the Alpha Vantage plugin reports EUR on every close on the
strength of the user's binding. Binding an INR-quoted symbol today would store
a rupee price as euros, roughly 90 times too high, and the core EUR check
cannot catch it. So holdings in other currencies cannot be priced or valued
until this exists.

This is a present need, not a future one: Indian stocks are held now, and more
will be bought over time by cost averaging (regular purchases).

## Considerations surfaced

**How the holdings are actually funded.** Money is transferred from a euro
account to an Indian bank account, and stocks are bought in the Indian demat
account with rupees. So the currency exchange happens at the remittance, and
the stock purchases are plain INR trades with no rate of their own.

**Proposed direction: INR is held in lots, like a security.**

- A remittance is a cross-unit entry: euros out, rupees in. It records the
  actual rate (X EUR paid, Y INR received) and creates an INR lot at that rate.
- A stock purchase spends rupees. It consumes INR lots FIFO, so the stock's
  euro cost is the euros actually sent for those rupees.
- Currency movement while rupees sit in India shows up as a realised FX gain or
  loss on the INR cash when it is spent, alongside the gains on the stocks.
- This reuses the FIFO lot machinery built for portfolio reporting, rather than
  adding a second mechanism.

The change it implies: today cash in the base currency is stored at price 1
and has no lots. FIFO extends from securities to a non-base currency unit.

**Recording never depends on a fetched rate.** The rule settled for
securities holds: a recorded entry carries the rate actually transacted, and a
rate fetched later never changes the books. Fetched rates are needed only to
value holdings at read time (INR cash, and INR-quoted stocks via their INR
close times the INR rate).

**Rates are prices.** Proposed: a rate is stored as an ordinary price — an
`INR` currency unit priced in EUR, in the existing `prices` table, fetched by
a price plugin. A parallel rates table would duplicate the staleness,
append-only and plugin logic prices already have.

**A close must know its quote currency.** Today EUR is implicit. An explicit
quote currency on a close is the one real schema change, and it is what turns
"rupees stored as euros, 90 times too high" from an accepted risk into a check
that can fail.

**Gains are in euros.** With lot costs in euros at the transacted rates,
realised and unrealised gains include the currency effect. As understood
(not verified), that is the basis a German resident's gain is measured on.
kohle's figures remain a cross-check, not a tax computation, as in portfolio
reporting.

**Importers.** The Indian bank and the demat account each need an importer
plugin for their statements; neither exists.

**Specs to revisit.** The importer and price-fetcher specs both put FX out of
scope and treat a non-base close as a per-unit failure.

## Directions rejected

- **Trusting the symbol binding as the currency assertion for non-EUR
  instruments**: the accepted risk for EUR-only today; does not scale to a
  portfolio with Indian holdings.
- **Valuing a stock purchase at the day's fetched rate**: makes a recorded
  cost depend on a fetched rate, and ignores what was actually paid for the
  rupees.
- **Treating each stock trade as the FX event**: matches a German broker
  filling in INR, which is not how these holdings are bought.
- **A separate table for exchange rates**: duplicates the price machinery.

## Open questions

- Which source provides INR rates and Indian closes, and does it share the
  provider question in `eu-price-provider`?
- How does the INR lot queue interact with INR that arrives other than by
  remittance (dividends, sale proceeds), and at what rate do those lots enter?
- What does "stale" mean for a stock that needs both a close and a rate, and
  which rate date is used when the two differ?
- Do reports show per-currency subtotals as well as euro totals?
- Is realised FX gain on cash reported by `realised`, or separately?
- Does `record` take the rate for a cross-currency entry explicitly, or derive
  it from the two amounts?
- What do the Indian bank and demat statement exports look like?
