# Multi-currency accounts and FX

## Overview

kohle can hold any unit, but it can value only euros. A fetched close is
accepted only in EUR, and binding an INR-quoted symbol today would store a
rupee price as euros, about 90 times too high, with no check to catch it.
Indian stocks are held now, in an Indian demat account funded from an Indian
bank account, and more are bought regularly (cost averaging). So net worth is
wrong for them until this lands.

This feature makes a non-EUR currency a unit held in FIFO lots, like a
security:

- A remittance (euros out, rupees in) creates an INR lot at the rate actually
  transacted.
- A stock bought with rupees takes its euro cost from the INR lots it uses up,
  so its cost is the euros actually sent.
- FX gain on cash is realised only when rupees are changed back into euros.

Rates are stored as ordinary prices, of the `INR` unit in EUR. A close names
its quote currency, so a rupee close can no longer pass as a euro close. Two
price plugins come with the feature: `ecb` for the rate and `nse` for Indian
closes. Every report still gives one total in euros and now also gives
subtotals per currency.

## Goals

- **Any non-EUR currency unit.**
  - The mechanism applies to every unit of kind `currency` other than the base
    currency. No code names INR.
  - Only INR is tested, and only INR is documented with examples.
  - The base currency stays EUR (`BASE_CURRENCY`) and cannot be configured.
- **Recording never reads a fetched price or rate.**
  - Every euro figure an entry depends on comes from one of two places: the
    entry itself (a transacted rate, or a rate the user supplies) or the
    ledger's own lots.
  - Fetching a rate later never changes a recorded cost, a realised gain or a
    lot.
  - `tests/test_price_guards.py` keeps holding for the recording path.
- **A remittance is two amounts.** `record` accepts an entry that takes
  `X EUR` from a euro account and puts `Y` of a currency unit into an own
  account.
  - X is the total debited, including any transfer fee.
  - The rate is derived as X / Y and is never typed. The resulting lot costs
    exactly X euros.
  - Testable: remitting 1,000 EUR for 90,000 INR creates one INR lot whose
    cost is 1,000.00 EUR.
- **Opening balances are the same shape.** There is no backdated history.
  - Existing INR cash and existing Indian stocks enter as opening entries.
    Each states a quantity and a total euro cost, taken from an opening
    account the user names.
  - The lot's cost is the stated euro amount.
  - This is the remittance form above with a different source account, not a
    second mechanism. It works the same for a security as for a currency unit.
- **A purchase paid in a currency unit takes its cost from that unit's lots.**
  - Buying N shares for Z INR consumes INR lots FIFO, in that account's queue.
  - The stock lot's euro cost is the summed euro cost of the INR consumed.
  - The purchase realises nothing.
  - Testable: remit 1,000 EUR for 90,000 INR, then 1,100 EUR for 100,000 INR,
    then buy shares for 120,000 INR. The stock lot costs
    1,000 + 1,100 × 30,000 / 100,000 = 1,330.00 EUR, and the remaining INR lot
    is 70,000 INR at 770.00 EUR.
- **An expense paid in a currency unit is valued at lot cost.**
  - The INR consumed FIFO gives the expense its euro amount.
  - No gain is realised.
- **Changing a currency back into euros realises FX gain.**
  - An entry taking `Y` INR out of an own account and putting `X EUR` into a
    euro account is recorded as two amounts, like a remittance.
  - It consumes INR lots FIFO.
  - Gain = X − the euro cost of the lots consumed.
  - It appears in `realised` as a row with unit `INR`, under the same total.
- **INR that arrives other than by remittance carries a rate the user
  supplies.**
  - This covers sale proceeds, dividends and interest.
  - The entry records the INR amount and a euro rate for it. Typically the
    user looks up the ECB rate for that day, but kohle never fills it in.
  - The new INR lot costs amount × rate.
  - A sale of an INR-quoted stock therefore realises its gain in euros on the
    sale date: proceeds = INR received × the recorded rate, less the stock
    lots' euro cost.
  - Recording such an inflow without a rate is a usage error.
- **Moves between own accounts carry lots.** INR moved from the bank account
  to the demat account is a move, as for securities in
  `portfolio-and-profit-reporting`. Lots keep their dates and costs, and
  nothing is realised.
- **Fail fast, as for securities.**
  - Spending more of a currency unit than an account's lots hold is a lot
    shortfall. The error names the unit, the account, the date and the
    shortfall.
  - A currency unit moving between an own account and a People account, in
    either direction, is refused with an error naming the entry.
  - Every report that needs the affected euro costs fails as a whole. Today
    that set is `positions` and `realised`, plus `balance` and `net-worth`
    wherever their euro cost for a currency-funded holding depends on lots.
- **Order-independent.** Recording an entry dated earlier than existing ones
  leaves every lot-derived euro cost exactly as a full replay of the ledger in
  `(entry_date, line id)` order would compute it. Entries on the same date are
  ordered by insertion, so this holds across distinct dates only.
  - Testable: recording the same entries, each on a distinct date, in two
    different insertion orders gives identical `positions`, `realised`,
    `balance` and `net-worth` output.
- **A close names its quote currency.**
  - `set-price-source UNIT PLUGIN SYMBOL` takes a quote currency, defaulting
    to EUR. The quote currency must be EUR or an existing currency unit.
  - A currency unit itself may now be bound. It must be quoted in EUR: a rate
    is a price of that unit in euros.
  - `fetch-prices` covers held currency units as well as held securities.
  - Core refuses a close whose currency differs from its binding's quote
    currency, with the reason named and nothing written for that unit. This
    replaces the "must be EUR" check.
  - Testable: an INR close for a unit bound with EUR, and a EUR close for a
    unit bound with INR, are each rejected and leave `prices` unchanged.
  - `alphavantage` reports the binding's quote currency. For that plugin the
    binding stays the user's assertion, which is accepted as a risk.
  - `file`'s CSV gains an optional `currency` column, which defaults to EUR.
- **`ecb` price plugin.**
  - It fetches the ECB daily euro reference rates and returns, for each
    requested currency code, its latest published rate as a price in EUR.
  - The symbol is the ISO code, e.g. `INR`.
  - It needs no API key.
  - Tests use recorded responses and make no network calls.
- **`nse` price plugin.**
  - It fetches the NSE bhavcopy (UDiFF, one file per trading day) and returns
    the official close for each requested symbol, in INR.
  - The symbol is the ISIN. The row matched is the one in the `EQ` series.
  - It starts from the latest weekday and steps back over holidays until a
    file exists.
  - It sends browser-like headers.
  - A file whose columns are not the ones expected is a plugin `Err`, never a
    guess.
  - An ISIN with no `EQ` row is `Unavailable(no_symbol)`.
  - Tests use recorded fixtures.
- **Valuing a holding quoted in another currency.**
  - Market value in euros = quantity × the latest close (in its quote
    currency) × the latest rate of that currency, each read as the latest on
    or before the date. Their dates do not have to match.
  - The status is the worse of the two. A stale status shows the older of the
    two dates.
  - If either the close or the rate is missing, the holding falls back to its
    euro cost and is marked `no price (at cost)`.
  - INR cash is valued at quantity × rate under the same rules.
  - `net-worth-history` applies this rule as of each sample date.
- **Per-currency subtotals in v1.**
  - `net-worth` and `positions` show a subtotal for each currency next to the
    euro totals. The subtotal gives the market value in that currency and in
    euros.
  - A holding's currency is:
    - for a currency unit, the unit itself;
    - for a security, its binding's quote currency;
    - for an unbound security, EUR.
  - The native-currency figure is `-` when any member of the subtotal has no
    close in that currency.
  - The euro total is unchanged by the subtotals and still equals the sum of
    the rows.
- **`positions`** shows `price` in the quote currency, labelled with it, and
  `market value`, `FIFO cost` and `unrealised gain` in euros. INR cash appears
  as a row; its unrealised gain is the unrealised FX gain.
- **Gains are economic, not tax.** The docs say plainly that kohle's euro gain
  is the economic gain:
  - cost is the euros actually sent;
  - proceeds use the rate recorded on the entry.

  This is not the basis German tax law converts on. As the user understands
  it (unverified), that basis uses the rate on the purchase date and on the
  sale date, with the currency itself treated as a separate private sale. No
  German broker certificate exists for these holdings to check kohle against.
- **Docs.** `prices.md`, `recording-entries.md`, `reports.md` and
  `accounts-and-units.md` are updated in the same PRs as the behaviour, with
  fictional accounts and amounts.
- **No regressions.** A ledger with no non-EUR currency unit produces exactly
  today's output from every command, and every existing test passes unchanged.

## Non-Goals

- **Importers for the Indian bank and the demat account.**
  - They will be follow-up briefs, one each, and are needed shortly before
    rollout.
  - Until they exist, entries are recorded by hand with `record`.
  - The importer contract's `CashRow` stays base-currency only in this
    feature.
- Backdated history of past remittances and purchases. Opening entries
  replace it.
- Indian tax: capital gains tax and tax withheld at source on dividends.
- German tax computation, as in `portfolio-and-profit-reporting`.
- Fees as separate lines. What was debited is what lands; a transfer fee
  becomes part of the INR lot's cost.
- Backfilling past rates or closes, and kohle supplying a rate when an entry
  is recorded.
- BSE closes.
- A configurable base currency.
- Conversions between two non-EUR currencies, hedging, and quote currencies
  that are not themselves quoted in EUR (no rate chains).
- Reporting dividend income.
- Currency units to or from People accounts. These are refused, as above.
- Xetra coverage, which stays in `eu-price-provider`.

## Technical Approach

- Python 3.12, `uv`, the existing `app → use_cases → services` layering and
  `Result` values.
- **Lots.**
  - `kohle/use_cases/lots.py` replays only `UnitKind.security` (`_replayed`).
    It must also replay non-base currency units.
  - Within an entry it must link the units. Today an INR credit with no INR
    debit in the same entry is a sale at its own line price, and a stock lot's
    cost is its own line's `unit_price`. Here, the cost of an INR-funded lot is
    the euro cost of the INR lots its entry consumed.
  - Moves between own accounts (`_move`) and People fail-fast
    (`SecurityMoveWithPeople`) already exist for securities and should cover
    currency units through the same path.
- **Euro balance of an entry.**
  - `validate_lines` balances an entry on Σ quantity × `unit_price` in euros.
  - An INR purchase or expense has no euro figure on its face. Its euro value
    is lot-derived, and an earlier-dated entry recorded later can change it.
  - The design decides how such lines are stored and balanced so that the
    order-independence goal holds. Options include balancing in the unit
    paid, or deriving the euro value only at replay.
  - The moving-average fold (`aggregate_by_unit`), which feeds `balance` and
    `net-worth`, must read the same euro costs.
- **Rates as prices.**
  - The INR rate is a row in `prices` for the `INR` unit, in EUR. ECB quotes
    INR per EUR, so the stored price is a reciprocal.
  - `QUANTITY` is `Numeric(20, 8)`, and SQLite stores NUMERIC as REAL. The
    design must keep the error of stored reciprocals negligible at realistic
    INR amounts, or store the rate as quoted.
- **Quote currency.**
  - `price_bindings` gains a quote-currency column (default EUR) in a new
    migration off the current head.
  - Every stored close is in its binding's quote currency, which makes
    rebinding to a different quote currency a hazard for existing rows. The
    design decides whether `prices` also records the currency per row, or
    whether such a rebinding is refused while rows exist.
  - `validate_close` in `kohle/use_cases/prices.py` compares against the
    binding instead of `BASE_CURRENCY`.
  - `set-price-source` stops refusing currency units (`NotASecurityUnit`), and
    `fetch-prices` selects held currency units too (`held_units` already folds
    every unit).
- **Reading.** `value_balances` in `kohle/use_cases/reporting.py` is the one
  place a close is read. It also reads the quote currency's rate as of the
  same date, through `latest_close`, which already takes `on_or_before`.
- **Plugins.**
  - `kohle/app/plugins/` holds the new plugins, registered under
    `kohle.plugins`.
  - Each HTTP call sits behind a seam the tests replace, as with
    `alphavantage`.
  - The `nse` details (URL, `ISIN`, `SctySrs`, `TradDt`, `ClsPric`, headers)
    are in `dev/inbox/eu-price-provider.md`.
  - The design confirms the ECB endpoint, how it marks a rate as final, and
    the ECB's terms of use.
- **`record` CLI.** It grows the two-amount form, for remittances, openings
  and reconversions, and a rate option for inflows of a currency unit. The
  design chooses the flags. `record-split` must be able to express the same
  entries.
- **Superseded non-goals.** The frozen specs `price-fetcher-plugin`,
  `importer-plugins-for-assets` and `portfolio-and-profit-reporting` put FX
  out of scope. This spec replaces those exclusions for currency units. The
  frozen files are not edited.

## Open Questions

- **Subtotal reach and layout.** This spec reads the user's "per-currency
  subtotals" as applying to `net-worth` and `positions` only. It does not
  apply them to `net-worth-history` or `balance`, and it groups unbound
  securities under EUR. The user should confirm, or say otherwise.
- **Euro balance and storage of lot-derived lines** (Technical Approach) is a
  design decision, not a requirement, but it is the largest one here.
- **ECB terms and endpoint, and NSE terms**, are unverified. Bhavcopy was
  accepted as a source by the user.
