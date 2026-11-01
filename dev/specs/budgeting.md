# Budgeting

## Overview

kohle records and classifies what was spent, but it has no record of what was
planned. Overspending in a category is only noticed by going looking for it.
This feature lets the user set a spending cap on an expense account, each cap
over its own period, and adds a report that compares actual spending with the
cap for every period. The report shows the overshoot and the undershoot.
Caps are estimates. A planned expense may turn out smaller, come later, or be
dropped, so a deviation is information and not an error. Each cap has its own
period because expenses recur on different rhythms (groceries monthly, the
Rundfunkbeitrag quarterly, insurance yearly). A monthly-only cap would make a
yearly payment blow its month every year, and that warning would soon be
ignored. Actual spending is never amortised. Periods are built on the single
recurrence vocabulary fixed by `configurable-net-worth-sampling`. This feature
builds that spec's two remaining kinds and defines no second vocabulary.

Personal-scale: the user is the only operator and consumer.

Command names are provisional. The roadmap puts `cli-command-naming` before
this feature, but the user chose to do budgeting first. The names below follow
today's flat style, and `cli-command-naming` may rename them.

## Goals

- **The two remaining recurrence kinds.** These are built exactly as the
  sampling spec defines them, and their meaning is pinned here:
  - `every N days|weeks|months from A`: every N units in step with A. A only
    fixes the phase. Occurrences run in both directions from it, so
    `every 3 months from 2026-01-15` also lands on 15 October 2025.
  - `yearly MM-DD`: that calendar day every year.
  - A month-based date keeps A's day, clamped to each month's length. It
    never drifts: from 31 January it lands on 28 February, then 31 March.
    `yearly 02-29` lands on 28 February in non-leap years.
  - Neither kind shifts to a working day.
  - Multi-year periods are written in months (`every 24 months from A`).
    There is no `years` unit.
- **Periods.** A period runs from one occurrence of the cap's recurrence to
  the day before the next. All seven kinds may define periods: `day 1` gives
  calendar months, and `workday 25` runs from payday to payday. The shifting
  kinds keep their shift under the Bundesland in force. Without a Bundesland
  entry they refuse and point to `move-state --from start <code>`, as
  `net-worth-history` does.
- **Caps are an effective-dated history per account.**
  - `set-cap <account> <amount> "<recurrence>" --from D` records a cap from
    D onward. `end-cap <account> --from D` records "no cap" from D onward.
    `--from` is required. D may be in the future.
  - An account has one entry in force at a time: an amount and a recurrence.
    Repeating an existing D for that account replaces the entry, which is how
    a mistake is corrected.
  - `list-caps` shows every account's full history, oldest first.
  - **Cut at D.** An entry taking effect at D ends the running period on
    D−1 and starts a new period at D. That new period ends the day before the
    new recurrence's next occurrence after D. A cap's first period starts at
    its D in the same way. A period cut short by D is marked short. Its cap
    is not prorated.
- **What may be capped.** Any expense account, leaf or parent, may be capped.
  A cap on a parent covers its whole subtree. Caps on a parent and a child are
  checked independently, and child caps need not add up to the parent's. A
  total cap is a parent account the user creates and caps. A cap on
  `Unclassified Expense` is refused, because that account has its own row. A
  cap on an income, asset or liability account is refused, and so is a cap on
  a People account. Caps are amounts in the base currency.
- **Spending is net.** The spending figure is debits minus credits on the
  capped account and its subtree, for lines dated within the period. Refunds
  reduce it, and a period can come out negative. Each line counts at the
  value it recorded. Expense splitting already leaves only the user's own
  share on the expense account.
- **The report.** `budget --from D --to D`:
  - The defaults are `--to` today and `--from` 1 January of `--to`'s year.
  - It shows every period of every cap that overlaps the range. A period is
    shown whole, with all its spending, and is not clipped to the range.
    Periods that start after today are not shown.
  - Columns: account, period start and end, cap, spent, and a signed
    over/under (positive means overshoot). Over-cap rows are marked, and so
    are short periods.
  - The period containing today is marked partial and shows the days passed,
    counting today: `day 12 of 31`.
  - There is no rollover. Each period stands alone.
  - One row shows the `Unclassified Expense` spending over the whole range.
  - One "uncapped" row shows the spending over the whole range on lines whose
    account had no cap in force, on itself or on any ancestor, on the line's
    date. `Unclassified Expense` is left out of it.
  - The report is a pure read. It leaves no `OperationGroup` and makes no
    price access.
- **All-or-nothing writes.** An invalid account, amount, recurrence or date
  writes nothing. The error names the bad part and lists the valid choices.
  Each successful change is one `Operation` in the audit trail.
- **Testable**
  - A cap of 300 with `day 1` from 2026-01-01 has the periods January,
    February, and so on. If `set-cap … 400 "day 1" --from 2026-03-10` is
    added, the March periods are 03-01–03-09 (short, cap 300) and 03-10–03-31
    (short, cap 400), and April is a full period with cap 400.
  - `every 1 months from 2026-01-31` gives the periods 01-31–02-27,
    02-28–03-30 and 03-31–04-29.
  - A cap from 2026-01-01 with `every 3 months from 2026-01-15` gives a first
    period of 01-01–01-14 (short), then 01-15–04-14.
  - `yearly 02-29` gives a period boundary on 2027-02-28.
  - 100 spent and 30 refunded on a capped account within one period shows
    70 spent.
  - A line on a child of a capped parent counts toward the parent's cap and
    does not appear in the uncapped row.
  - An end-cap entry from D puts lines on that account dated D or later into
    the uncapped row.
  - A line in `Unclassified Expense` appears only in the unclassified row.
  - `set-cap` on `Unclassified Expense`, on an income account, or with an
    invalid recurrence leaves `list-caps` output and the `operations` row
    count unchanged.
  - `budget` leaves the `operations` and `operation_groups` row counts
    unchanged and calls no price plugin.
  - `net-worth-history` output is unchanged by this feature.
  - Existing tests pass.
- **The README** documents caps, the two new recurrence kinds, how periods
  are formed (including cut at D and short periods), the commands, and the
  report's rows and columns.

## Non-Goals

- **Savings targets**, and showing what is left over as a goal. The user
  treats savings as assets. A contribution target on an asset account is
  captured in `dev/inbox/savings-targets.md` for 2027.
- **Rollover** of unspent cap or overspend between periods.
- **Prorating or amortising** caps or actual spending.
- **A special total cap.** A capped parent account covers it.
- **A cash-flow view.** It moves to `debts-and-liabilities`.
- **Expected-payment flags.** These are captured in
  `dev/inbox/expected-payments.md` for 2027.
- **Merging with envelopes.** Caps move no money.
- **Entering caps through `$EDITOR`.**
- **Raw RRULE input**, `every N years`, or any other addition to the shared
  recurrence vocabulary.
- **Caps in a unit other than the base currency.**
- **An `--account` filter** on the report.
- **Alerts or notifications**, after an import or from cron.
- **Any TUI**, and machine-readable output.
- **Final command names** (`cli-command-naming`).

## Technical Approach

- Python 3.12, SQLAlchemy 2.0, and a packaged Alembic migration. There is no
  new dependency.
- The two kinds extend `kohle/use_cases/recurrence.py`, the one vocabulary,
  keeping its pure parse, render and occurrence functions. Whether the
  internal form becomes RRULE or stays the current ADT is the architect's
  call. The user syntax is fixed either way.
- Turning occurrences into periods, cutting at D, and the
  covered/uncapped/unclassified attribution are pure functions of the cap
  history, the Bundesland history, the range and the lines. They have no
  session and no price access.
- Spending per account over a period is already computable from the journal
  (as `entries-in-period` does). The report reads from there.
- Caps are ledger data, like the Bundesland history. They live in the ledger
  and travel with snapshots. They are never device settings, never go in
  `config.toml`, and are not a general key/value channel. This is the same
  reading of `app-initialization`'s "no further configuration mechanism"
  that the sampling spec relies on.
- Writes go through `UnitOfWork` and `crud_create`. Parsing and validation
  return `Result` with domain error values.

## Dependencies

No frozen spec is contradicted. The two kinds are those
`configurable-net-worth-sampling` already specifies and assigns to this
feature, and that spec stays untouched.

## Open Questions

None blocking. Two small calls, with a default each:

- **Do the new kinds become valid in `set-sampling-rules`?** One shared
  parser suggests yes (for example, `salary: every 2 weeks from …` for a
  fortnightly salary). The sampling spec does not forbid it. Default: yes,
  with `net-worth-history` unchanged for existing rule lists. If the user
  wants sampling restricted to the first five kinds, say so before design.
- **A cap of 0.** Default: an amount of 0 or more is valid. 0 means any
  spending is overshoot. A negative amount is refused.

Left to design: the storage shape of the cap history, the internal recurrence
form, and the layout of `list-caps` and `budget`.
