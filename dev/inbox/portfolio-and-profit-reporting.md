# Portfolio and profit reporting

## Goal

Report three things from one ledger, across every account type:

- what is held;
- what it is worth now;
- what was gained on things sold.

The problem behind it: these look like three features but are two very different
computations. Current standing needs only quantity and today's price and no
history at all. Profit needs to know which specific units were sold, because
they were bought at different prices. Conflating them leads to building lot
machinery for reports that never needed it.

## Now covered elsewhere

"What it is worth now" has moved to `market-value-reporting`, so it is no
longer open here. That spec covers:

- `balance` and `net-worth` value each holding at its latest stored close,
  read through `latest_close`;
- the at-cost figures stay where they are;
- a stale close is still used, but is marked with its date;
- a missing close falls back to cost and is marked;
- a summary line counts the estimated holdings;
- `--max-age-days` sets the staleness threshold.

Everything below is what is left.

## Deferred scope

- **Positions view.** A dedicated holdings view for ETFs and stocks: one row
  per position, across accounts, rather than per-account `balance` output.
- **Unrealised gain.** Market value minus cost, per position and in total.
- **Realised profit.** FIFO replay of a unit's lines in date order. FIFO is
  forced for German securities, so no choice needs recording. No lot linkage
  is stored.
- **Net worth over time.** This needs closes at past dates. The `prices`
  table is already append-only and unique per `(unit_id, price_date)`, so
  history builds up from repeated `fetch-prices` runs. Backfill remains a
  price-fetcher non-goal, so the history only starts from the first fetch.

## Already true in the code

- **The importer contract carries sales the way it carries purchases.**
  `SecurityRow` (`kohle/plugin/importer_plugin.py`) is typed. It has
  `entry_date`, `instrument_identifier`, a signed `quantity` (negative means a
  sell) and `unit_price`. Manual `record --to-unit/--to-price` produces the
  same lines. This settles the dependency the profit consideration below
  names, for imported trades.
- **Lines come back in replay order.** `account_lines_service` returns lines
  ordered by `(entry_date, line id)`. The moving-average fold
  (`aggregate_by_unit` / `_RunningCost` in `kohle/use_cases/journal.py`)
  relies on that order, and a FIFO replay needs the same one. `held_units`
  already folds a unit's quantity across all accounts.
- **Cost is currently moving-average, not FIFO.** `balance`'s
  `average cost`, and the at-cost totals in `net-worth`, both come from that
  fold. They are not FIFO.
- **Realised gain is posted nowhere.** `record` derives a sale's
  counter-line at the sale price and posts no gain to an income account
  (expense-splitting design §9.3). Realised profit can therefore only come
  from a replay. No account balance holds it.
- **Price history exists. Point-in-time reads do not.**
  - The tables `prices` and `price_bindings` exist.
  - `latest_price_service` and `latest_close`
    (`kohle/use_cases/prices.py`) read only the latest close.
  - Net worth over time needs a "close on or before date D" read, which does
    not exist yet.
- **Structural guard.** `tests/test_price_guards.py` keeps
  `kohle/use_cases/journal.py` free of any price reference. Every report in
  this brief that reads prices must therefore sit outside that module, as
  market valuation already must.

## Considerations surfaced

Positions are cheap: holdings times latest price, per unit. No purchase history
required.

Profit is a replay. Because FIFO is forced for German securities, no choice
needs recording — walking a unit's lines in date order and consuming purchases
against sales reconstructs the lots at report time. This depends entirely on
sales carrying quantity, price and date the way purchases do, which is why the
importer contract matters to this brief.

Net worth is a recursive rollup over the account tree. It is only trustworthy
because of the leaf-only posting rule from the ledger design — if anything ever
posts to a parent, every rollup is quietly wrong. Bank reconciliation compares
at the parent level while postings live in children, so reports need to know
which level a given question is asked at.

This is the least specified area of the whole vision, and plausibly hides the
most work. "Reports" has been used throughout the discussion without ever being
pinned down.

## Directions rejected

Storing explicit lot linkage — sales pointing at the purchases they consumed.
Unnecessary when the consumption order is forced, and it would have to be
maintained on every edit.

## Open questions

- What is the actual report inventory? Positions, profit and net worth are
  established; everything else is guesswork.
- CLI output shape — tables, or something a spreadsheet can consume?
  `market-value-reporting` set a precedent for `balance` and `net-worth`:
  tabulate tables, a greppable status column and a plain summary line. It
  did not decide this for new reports.
- Does the TUI get its own reporting views, or does it stay an editor over the
  same use cases?
- What cost basis should unrealised gain use? The candidates are the
  moving-average cost that `balance` already shows, or the cost of the FIFO
  lots still held, which matches realised profit and tax. They differ once a
  position has been partly sold.
- For net worth over time, which dates should be sampled, and how should a
  date with no close be valued? Possible answers include the last close on
  or before that date, or cost, with the same marking as market value.
