# Market value reporting

## Overview

`balance` and `net-worth` report every holding at recorded cost today. The
price fetcher now stores daily closes, but nothing reads them. This feature
values each holding at its latest stored close, alongside the existing
at-cost figures. It reads stored prices and never replaces cost. When a close
is old or missing, the report still gives a value and marks it, so the total
always covers every holding and every estimate can be seen. Reports never
fetch and never write prices. The separation from the price-fetcher spec
stays structural: nothing on the reporting path writes prices, and nothing on
the recording path reads them. This is the first consumer of `latest_close`.
It covers only valuation at the latest close. The rest of
`portfolio-and-profit-reporting` stays deferred (see Non-Goals).

## Goals

- **`balance` gains market value per unit and a market total.**
  - Each unit row keeps `unit`, `quantity` and `average cost`, and gains four
    columns: price, price date, market value and status.
  - The new columns go *before* `average cost`, so `average cost` stays the
    last column. The column order is: `unit`, `quantity`, `price`,
    `price date`, `market value`, `status`, `average cost`.
  - Existing values stay as they are.
  - When the account holds at least one non-base-currency unit with nonzero
    quantity (M > 0, as defined under the estimate summary), two new lines
    go at the end of the output: `Market value: X`, then the estimate
    summary. When M = 0, for example a euro-only expense category, neither
    line is printed (confirmed by the user).
  - The label is `Market value:`, not anything containing "Total":
    `tests/test_cli.py` asserts that "Total" never appears in the output for
    a multi-unit account.
  - `Market value: X` sums the unit rows only, never the
    `Total (base currency)` restatement row, which would count a
    single-currency account twice.
  - There is no new at-cost total. The cost of each row is already visible
    as quantity × average cost.
  - `No holdings` output is unchanged and gets neither line.
- **`net-worth` gains a market total.**
  - Each row gains the same four columns, placed by the same principle: the
    existing last column stays last. The column order is: `section`, `unit`,
    `quantity`, `price`, `price date`, `market value`, `status`, `at cost`.
  - The existing `Net worth (at cost): X` line stays byte-identical. Two new
    lines always follow it: `Net worth (at market): X`, then the estimate
    summary.
  - Both totals are reported. The at-cost figures never depend on a fetch or
    on the price table.
- **Valuation rule, per unit row with nonzero quantity:**
  - **Base currency** (`BASE_CURRENCY`): market value = quantity × 1. No price
    lookup.
  - **`Fresh` close:** quantity × close price, status `fresh`.
  - **`Stale` close:** still quantity × close price, status
    `stale (YYYY-MM-DD)` with the close's date.
  - **`NoClose`:** market value = quantity × average cost (the cost fallback),
    status `no price (at cost)`. This covers a unit that was never fetched, an
    unbound security, and any non-security unit, such as a commodity or a
    non-EUR currency. These are not told apart. Saying why a unit has no close
    is `fetch-prices`' job.
- **Base-currency rows have no status** (confirmed by the user). They render
  `-` in the status, price and price-date columns via tabulate's
  `missingval="-"`, the convention `balance` already uses for "not
  applicable". `net-worth` passes no `missingval` today, so it gains
  `missingval="-"`. Why: a base-currency value is exact rather than an
  estimate, and it is not derived from a close. Labelling it `fresh` would
  claim that a price was fetched. Adding a fourth status word would grow the
  vocabulary that people grep for, and nothing would be gained.
- **Zero-quantity rows are not holdings** (confirmed by the user).
  `aggregate_by_unit` still emits them, for example a position that has been
  sold out. They keep their existing at-cost rendering, get market value 0
  and `-` for status, price and price date, and are not counted in the
  summary. No close is looked up for them.
- **Estimate summary.** One line after the market total reads
  `K of M holdings estimated (S stale, C at cost)`.
  - M is the number of non-base-currency rows with nonzero quantity.
  - K = S + C.
  - Base-currency rows are not counted, because they can never be estimates.
  - In `net-worth` the line always prints. When K = 0 it prints as
    `0 of M holdings estimated`, so `net-worth`'s output shape does not
    depend on the data.
  - In `balance` the line, like the market-value line before it, prints only
    when M > 0. When M > 0 and K = 0 it prints as `0 of M holdings
    estimated`.
- **Threshold flag.** `balance` and `net-worth` both take
  `--max-age-days N`, a non-negative integer with default 7. The value is
  passed through to `latest_close`'s `max_age_days`. There is no persistent
  setting and no config mechanism. This settles the price-fetcher spec's
  open item "how the staleness threshold is configured".
- **Receivables stay at face.** People-subtree rows are base currency and are
  valued at quantity × 1, exactly as today.
- **One valuation per unit.** In each section, a unit held across several
  accounts appears as one row: `account_balance` already folds the subtree,
  and `NetWorth` already folds all own accounts. That row is valued with one
  `latest_close` read, applied to the summed quantity.
- **Testable:**
  - Fixtures produce each status: `fresh`, `stale (date)` and
    `no price (at cost)`.
  - A `NoClose` row's market value equals quantity × average cost.
  - The net-worth market total equals the sum of the market values of all
    rows in both sections. The at-cost total is unchanged from today on the
    same ledger.
  - The `balance` market total equals the sum of its unit rows' market
    values; the `Total (base currency)` restatement row is not summed.
    `balance` prints no at-cost total.
  - A euro-only `balance` (M = 0) prints neither the `Market value:` line nor
    the summary line. A `balance` of a mixed account, holding base currency
    and at least one other unit with nonzero quantity, prints both.
  - `net-worth` prints `Net worth (at market): X` and the summary line on
    every ledger, including `0 of M holdings estimated` when K = 0.
  - `average cost` is the last column of every `balance` row, and `at cost`
    is the last column of every `net-worth` row.
  - Boundary: with `--max-age-days 7`, a close 7 days old is `fresh` and one
    8 days old is `stale`. The same pair is checked at a non-default N.
  - The summary's K, S, C and M are correct on a ledger that mixes base
    currency, fresh, stale, no-close and zero-quantity rows.
  - Running `balance` and `net-worth` leaves the `prices` row count unchanged
    and writes no `Operation` row. Their CLI callbacks do not reference
    `load_price_plugins`, `PriceFetcherPlugin`, `call_price_plugins`,
    `AppendPrices` or `add_price_service`.
  - Every existing `balance` and `net-worth` test passes unchanged, including
    `tests/test_price_guards.py::test_no_price_plugins_means_no_output_change`.

## Non-Goals

All of the following stay in `portfolio-and-profit-reporting`:

- an unrealised-gain column (market value − cost);
- realised profit;
- FIFO lot replay;
- a positions/holdings command;
- net worth over time.

Also out of scope:

- Fetching from a report, lazily or on demand. A report is a pure read of
  stored history.
- A persistent or configured staleness threshold. The flag is the only knob.
- Distinguishing unbound units from never-fetched ones in the status.
- FX conversion, or valuing non-EUR currency units at anything but cost.
- A new output format (CSV/JSON). The output stays as tabulate tables plus
  plain lines.
- TUI views (see `tui-wiring`).

## Technical Approach

- **Read function.** Use `latest_close(ctx, unit_id, today, max_age_days)` in
  `kohle/use_cases/prices.py`. It returns `Fresh(close) | Stale(close) |
  NoClose()`, and every report must handle all three; mypy enforces this
  through the union. No other price read is added. `today` comes from the
  CLI (`date.today()`) and is a parameter all the way down, so tests can pin
  the boundary without a clock.
- **Unit id.** `UnitBalance` (`kohle/use_cases/journal.py`) carries only
  `unit_identifier`, while `latest_close` takes a `unit_id`. Price-fetcher
  design §8 leaves to this feature the choice between two options:
  - carry the id on `UnitBalance`;
  - resolve it via `get_unit_by_identifier_service`.

  The design decides which.
- **Where valuation lives.** This is a structural constraint, not a
  preference:
  - `tests/test_price_guards.py` forbids `kohle/use_cases/journal.py`, which
    holds `QueryAccountBalance`, `NetWorth`, `NetWorthReport`, `_at_cost` and
    `aggregate_by_unit`, from referencing `Price` or importing any of
    `kohle.use_cases.prices`, `kohle.services.price_services` or
    `kohle.plugin.price_plugin`, even transitively.
  - `prices.py` already imports `BASE_CURRENCY` and `held_units` from
    `journal.py`.

  So the market valuation cannot go into `journal.py`. It has to sit in a
  module that may import both, either a new reporting use-case module or
  composition in the CLI. The design picks which and decides whether
  `QueryAccountBalance`/`NetWorth` move. Expense-splitting design §9.1 named
  FIFO as the trigger for splitting `journal.py`, and this guard may move
  that point earlier. Whatever the choice, all the `latest_close` reads for
  one report happen inside a single `UnitOfWork` transaction, alongside the
  balance fold, as price-fetcher design §8 intended.
- **At cost is untouched.** `_at_cost` and `NetWorthReport.own_at_cost`,
  `receivables_at_cost` and `net_worth_at_cost` keep their meaning:
  `quantity × average_cost` and never `sum(line.value)` (expense-splitting
  design §9.3). The `NoClose` fallback reuses exactly that per-row figure.
  Market value follows the seam from expense-splitting design §9.4: per row,
  quantity × per-unit value.
- **Output that changes shape** (the design must handle all of these):
  - `balance_cmd` table (`kohle/app/cli/cli.py`) gains four columns between
    `quantity` and `average cost`, followed, only when M > 0, by the
    `Market value: X` line and the summary line.
    - The `Total (base currency)` restatement row renders `-` in the new
      columns except market value, which is the quantity. It is never
      included in `Market value: X`.
    - The new columns must not mix `str` into numeric columns, because of the
      `floatfmt`/`missingval` trap documented in `balance_cmd`. That means
      price and market value use `None` → `-`, never a string.
  - `_net_worth_rows` / `net_worth_cmd` table gains the same four columns
    between `quantity` and `at cost`, and its `tabulate` call gains
    `missingval="-"`. The `Net worth (at market): X` line and the summary
    line follow the existing at-cost line.
  - README, one section per slice:
    - "Net worth": the net-worth slice updates the example output and
      rewrites the at-cost-only paragraph ("Every figure is reported at
      recorded cost ...").
    - "Reading the ledger", which describes `balance`: the balance slice
      updates the example output and replaces the "no market valuation yet"
      sentence.
- **Rounding.** Totals are summed as exact `Decimal`s and printed with
  `Decimal`'s `:.2f`, while table cells go through tabulate's `floatfmt`. So
  the printed cells may differ from the printed total by a cent while the
  `Decimal` totals are exact, as the at-cost total already can. Tests compare
  `Decimal`s, not printed cells.
- **Existing tests that constrain layout:**
  - `tests/test_cli.py::test_balance_renders_none_average_cost_as_dash_without_breaking_other_rows`
    reads `average cost` as the *last* whitespace token of a row
    (`split()[-1]`). Keeping `average cost` last is what lets it pass
    unchanged.
  - `test_no_price_plugins_means_no_output_change` keeps passing because
    reports read only the table, and its script stores no closes.
  - The net-worth CLI test asserts `Net worth (at cost): -32.00` verbatim.
  - `tests/test_net_worth.py` asserts the at-cost properties.
- **Inputs.** `--max-age-days` is a click `IntRange(min=0)` on both commands.
  0 means only today's close is fresh.

## Open Questions

None blocking.

The user's decision on `balance`'s M = 0 output, made after the design's
"conflicts and gaps" review, is written into the Goals bullets on `balance`
and on the estimate summary, the Testable list, and Technical Approach under
"Output that changes shape". It replaces "the output shape does not depend on
the data" for `balance` only; `net-worth` is unchanged.

The user answered all three questions from the first draft, and the answers
are written into the requirements above:

- **`balance` totals.** `balance` gets a market total and the summary line
  at the end of its output, and no at-cost total. `net-worth` keeps both
  totals. Recorded in the Goals bullets on `balance` and `net-worth`, and in
  the Testable list.
- **Column order.** The new columns go before `average cost` in `balance`
  and before `at cost` in `net-worth`, so the existing last column stays
  last and the dash test passes unchanged. Recorded in the Goals bullets,
  with both column orders spelled out, and in Technical Approach under
  "Output that changes shape" and "Existing tests that constrain layout".
- **Base-currency and zero-quantity rows.** Both choices are confirmed.
  Recorded in the Goals bullets on base-currency rows and zero-quantity rows.
