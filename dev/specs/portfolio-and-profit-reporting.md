# Portfolio and profit reporting

## Overview

`market-value-reporting` values each holding at its latest stored close in
`balance` and `net-worth`. This feature adds the three reports that work left
deferred, as new read-only CLI commands:

- **`positions`**: what is held across every depot, valued at the latest
  close, with FIFO cost and unrealised gain.
- **`realised`**: FIFO realised profit, one row per sale.
- **`net-worth-history`**: net worth at sampled past dates.

The value of these reports is a consolidated view across brokers that agrees
with the ledger. Brokers already do per-depot FIFO and issue tax certificates.
kohle's realised figure is gross (before fees and tax) and serves as a
cross-check against them. It is not a tax computation.

Two different computations sit underneath:

- **Standing** (positions, net worth) needs quantity and a close.
- **Profit** needs to know which lots were sold.

FIFO is forced for German securities, so lots are reconstructed by replaying
the ledger at report time. Nothing is stored. `balance` and `net-worth` do not
change.

## Goals

- **Every new report is a pure read.**
  - It writes no row and no `Operation`.
  - It never calls a price plugin.
  - It reads only closes that are already stored.
  - The same ledger, the same `prices` table and the same `today` give the
    same output.
- **FIFO replay.**
  - There is one queue per (depot, security). A depot is an own leaf account
    holding the security.
  - A unit's lines are consumed in ledger order, `(entry_date, line id)`.
  - A sale consumes the oldest lots in that depot first.
- **Moves between own depots are not sales.**
  - They realise nothing.
  - The lots consumed from the sending depot move to the receiving depot with
    their original purchase dates and costs.
  - The receiving queue is ordered by those original purchase dates.
- **Fail fast on an inconsistent ledger.**
  - If a sale or move-out exceeds the lots that depot holds, `positions` and
    `realised` fail as a whole and print nothing.
  - The error names the unit, the account, the entry date and the shortfall.
  - This is a data error, unlike a missing close.
  - **A security moving between an own depot and a People account**, in
    either direction, is not supported for now. `positions` and `realised`
    fail the same way, with an error that names the entry.
- **A missing or stale close is not an error.** It keeps `net-worth`'s rule:
  the report gives a figure and marks it (`fresh`, `stale (YYYY-MM-DD)`,
  `no price (at cost)`).
- **`positions`**
  - It shows one row per security with nonzero quantity, summed across all
    own accounts, which is `net-worth`'s own-accounts partition, excluding the
    People subtree.
  - The columns are: `unit`, `quantity`, `price`, `price date`,
    `market value`, `status`, `FIFO cost`, `unrealised gain`.
  - `FIFO cost` is the cost of the lots still held, summed over depots.
  - `unrealised gain` is `market value − FIFO cost`.
  - A `NoClose` row falls back to its FIFO cost, so its unrealised gain is 0,
    and it is marked.
  - After the table come three total lines (market value, FIFO cost,
    unrealised gain), then the `K of M holdings estimated (...)` line.
  - It takes `--max-age-days N` (default 7), the same flag as `net-worth`.
  - It covers securities only for now. **Requirement:** extending it to
    commodities or other non-base units later must not need a redesign. The
    row and valuation shape must not assume `kind == security` beyond the
    filter that selects the rows.
- **`realised`**
  - It shows one row per sale: `date`, `account`, `unit`, `quantity`,
    `proceeds`, `FIFO cost`, `gain`.
  - Proceeds are the quantity sold × the sale line's recorded unit price.
  - `--year YYYY` filters rows by sale date. The replay always runs over the
    full history, because the lots come from earlier years. Without
    `--year`, every sale from all years is listed under one total.
  - A `Realised gain: X` total line closes the output.
  - Moves between own depots never appear as rows.
- **`net-worth-history`**
  - **Sample dates.** These are the calendar 15th of each month and the
    month's period end, plus a final row dated `--to` when `--to` is not
    itself a sample date. `--to` defaults to today, so the "today" row
    appears only when `--to` is today or omitted. A past `--to` ends the
    report with a row dated `--to`. The 15th never moves.
  - **`--period-end month-end|last-working-day`**, default
    `last-working-day`. It sets the period end as the salary credit date:
    - `last-working-day` is the last working day of the month, i.e. the
      salary day.
    - `month-end` is the calendar last day of the month.
    - The row is dated that day and includes every line dated on or before
      it, so the salary is in.
  - **Working day** means Monday to Friday, and none of the following:
    - a public holiday of the chosen Bundesland, from the `holidays`
      package (a new dependency);
    - 24 December or 31 December. German banks are closed on both, so no
      salary is credited.
  - **The state is exposed to the user.** The lightest form is
    `--state XX` on `net-worth-history` (default `BY`). An unknown code is a
    usage error before anything is read. It has no effect with
    `--period-end month-end`. Where this setting should live is an open
    question; see Open Questions.
  - **Range.** `--from YYYY-MM-DD` / `--to YYYY-MM-DD` set the range. The
    default runs from the earliest ledger entry date to today. A date after
    today, or `--from` later than `--to`, is a usage error.
  - **Valuing date D.** Each date is valued by `net-worth`'s rule as of D:
    - the lines dated on or before D, own accounts plus receivables;
    - each non-base unit at its last stored close on or before D, fresh or
      stale relative to D under `--max-age-days` (default 7);
    - when there is no such close, the unit falls back to moving-average cost
      and is marked. This covers every date before price history began,
      because closes are never backfilled.
  - The columns are: `date`, `at cost`, `at market`, `estimated`, where
    `estimated` holds `K of M`.
  - **When `--to` is today or omitted, the final row equals `net-worth`
    today**: the same at-cost total, the same at-market total, and the same K
    and M.
  - It does not run FIFO, so the fail-fast lot check does not apply to it.
- **Output** follows the `market-value-reporting` conventions:
  - tabulate tables plus plain summary lines;
  - `missingval="-"`;
  - `.2f` money;
  - totals summed as exact `Decimal`s;
  - a greppable status column.
- **The README** documents all three commands. It states that `balance`'s
  `average cost` is a moving average, while `positions` and `realised` use
  FIFO.
- **Testable:**
  - A buy-buy-sell sequence in one depot gives the FIFO realised gain and the
    FIFO cost of the remaining lot.
  - The same securities held in two depots replay independently.
  - A move from depot A to depot B produces no `realised` row. B's later sale
    consumes A's original lots at their original cost and in their
    purchase-date order.
  - A sale beyond the depot's lots makes `positions` and `realised` exit
    non-zero, with the unit, account, date and shortfall in the message and
    no table printed.
  - A security moved between an own depot and a People account makes
    `positions` and `realised` exit non-zero, naming the entry.
  - `realised --year` lists only that year's sales. Their gains still use
    lots bought in earlier years. Without `--year`, it lists every sale
    under one total.
  - `net-worth-history --to` with a past date that is not a sample date ends
    with a row dated `--to` and has no row dated today.
  - `positions` totals equal the sums of the rows. `unrealised gain` equals
    `market value − FIFO cost`. A `NoClose` row has gain 0 and is marked.
  - With `--period-end last-working-day --state BY`, a month whose last day
    is a Saturday, or a Bavarian holiday, samples the preceding working day.
    With `month-end`, the sample is the calendar last day.
  - With `last-working-day`, December's period end is 30 December when that
    is a weekday. When 30 December is a weekend day, it moves to the
    preceding working day: for example, the 2028 period end is Friday
    29 December. 24 and 31 December are never sample dates under
    `last-working-day`.
  - A history row includes a line dated on its sample date (the salary) and
    excludes the next day's.
  - A past D uses the last close on or before D, never a later one. A date
    before the first close is at cost and marked.
  - With `--to` omitted, the final `net-worth-history` row matches
    `net-worth`'s totals and K, M on the same ledger and `today`.
  - All three commands leave the `prices`, `operations` and
    `operation_groups` row counts unchanged. Their code references no price
    writer or plugin loader (extend `tests/test_price_guards.py`).
  - Every existing test passes unchanged.

## Non-Goals

- Fees and commissions. They are not modelled (importer spec), so realised
  gain is gross.
- Dividends and other income.
- German tax computations: Teilfreistellung, Vorabpauschale,
  Sparerpauschbetrag, loss pots. Brokers do this.
- FX, and valuing non-EUR currency units at anything but cost
  (`multi-currency-and-fx`).
- Price backfill, and manual price entry.
- CSV, JSON or any other output format.
- TUI views. This feature is CLI only, with use cases a future TUI can call
  (`tui-wiring`).
- Any change to `balance` or `net-worth`.
- Storing lot linkage. Lots are derived because the consumption order is
  forced, and stored links would have to be maintained on every edit.
- Positions for non-security units. These are deferred, but must be allowed
  by the design (see Goals).

## Technical Approach

- **Python 3.12**, with the existing `app → use_cases → services` layering
  and `Result` values. One `UnitOfWork` per report, reading only.
- **Already true in the code:**
  - **Sales carry what a replay needs.**
    - `SecurityRow` (`kohle/plugin/importer_plugin.py`) has `entry_date`,
      `instrument_identifier`, signed `quantity` (negative is a sell) and
      `unit_price`.
    - Manual `record --to-unit/--to-price` produces the same lines.
  - **`account_lines_service` returns lines in `(entry_date, line id)`
    order**, which both the moving-average fold and the FIFO replay need.
  - **Cost today is moving-average** (`aggregate_by_unit` / `_RunningCost`
    in `kohle/use_cases/journal.py`). It feeds `balance`'s `average cost` and
    `net-worth`'s at-cost totals. FIFO is new and does not replace it.
  - **Realised gain is posted nowhere.** `record` posts a sale's
    counter-line at the sale price (expense-splitting design §9.3), so only a
    replay yields it.
  - **Only the latest close can be read today.** `latest_close`
    (`kohle/use_cases/prices.py`) is the only price read.
    `net-worth-history` needs a "last close on or before D" read, with
    staleness relative to D. The market-value design names `value_balances`
    as the one place a read would switch, since `today` already flows down.
  - **`prices` is append-only, with one row per `(unit_id, price_date)`.**
    History grows only through repeated `fetch-prices` runs. Plugin rate
    limits bound how dense that history is, not the reports.
- **Structural guard.** `tests/test_price_guards.py` forbids
  `kohle/use_cases/journal.py` from referencing prices, even transitively.
  Price-reading reports go in `kohle/use_cases/reporting.py`, which is the
  home the market-value design reserved for them. A FIFO replay with no price
  reference may live with the fold or in its own module; the design decides.
- **Reuse:**
  - `ValuedBalance`, `value_balances`, `at_market`, `summarise`;
  - `_market_columns`, `_estimates_line`, `MAX_AGE_DAYS`;
  - `net_worth(ctx)`;
  - `UnitBalance.unit_id`.

  `positions` and `net-worth-history` keep the status vocabulary and the
  estimate line identical to `net-worth`'s.
- **FIFO needs the account on each line.** The replay is keyed by
  `(account, unit)`, and the design decides how a move between own depots is
  recognised from an entry's lines.
- **Working days.**
  - The `holidays` package is pinned in `pyproject.toml` like every other
    runtime dependency.
  - The "is a working day in state S" rule sits behind one small predicate:
    a weekday, not a state public holiday, and not 24 or 31 December. The
    calendar source can then change without touching sampling.
  - `today` and all dates are parameters below the CLI, as in market-value
    reporting.
- **Fail fast as a value.** The lot shortfall is a domain error returned as
  `Err`, never raised, and the CLI maps it to a non-zero exit like any other
  error.

## Open Questions

- **Persistent setting for `--state` and `--period-end`.** The user wants the
  Bundesland configurable and exposed. kohle has no configuration mechanism:
  - persistent state is the database only;
  - environment variables are read only by price plugins;
  - the market-value precedent is "the flag is the only knob".

  The PRD asks for flags, the lightest mechanism. Whether a persistent
  setting (a DB row with a setter command, or `KOHLE_*` env vars) is worth
  introducing is the architect's call.
