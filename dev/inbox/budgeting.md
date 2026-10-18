# Budgeting

## Goal

Let the user set a spending cap per expense category, each over its own
period, and see at the end of a period how far actual spending overshot the
estimate.

The problem behind it: kohle records and classifies what was spent but has no
notion of what was planned, so overspending in a category is only noticed by
going looking for it.

## Considerations surfaced

**A cap, not a savings target.** Agreed: the purpose is catching overspending
per category. What is left over at the end of a period is not the point.

**Budgets are estimates.** A planned expense may turn out smaller, later, or
dropped entirely. The report compares and shows the overshoot (and
undershoot); it does not treat a deviation as an error.

**Each cap has its own period.** Expenses recur on different rhythms: every
week, every nth week, every month, every n months, every nth day, every year
(a bulk insurance payment, for example). A monthly-only cap would make a
yearly payment blow its month every year, and the warning would be learned to
be ignored. So a cap carries its own period — insurance per year, groceries
per month, something fortnightly per two weeks — and is checked against
spending inside its own window. Actuals are never amortised (1,200 a year
shown as 100 a month), because that bends the figures away from what the
ledger says.

**Categories are accounts.** Expense categories are ordinary expense accounts
in the hierarchy, and a parent's balance is the sum of its children. A cap on
a parent naturally covers its subtree.

**Unclassified spending is shown.** Spending still in `Unclassified Expense`
appears as its own line, so a large unclassified bucket reads as unbudgeted
spending rather than silently flattering every category.

**Actuals already exist and the report is a pure read.** Spending per account
over a period is already computable; the comparison should be a read in the
same spirit as the other reports.

**One recurrence vocabulary for kohle.** The periods here (every n days,
weeks, months; yearly) overlap with the salary-day sampling rules in
`configurable-net-worth-sampling` (fixed day, nth weekday, last working day).
Define one recurrence vocabulary and use it in both places, rather than two
near-identical ones. With this many kinds, RFC 5545 RRULE as the internal
representation is worth reconsidering, even if the user-facing syntax stays
friendlier.

**Expected-payment flags are optional.** Knowing a recurring payment is
expected, and flagging one that has not appeared (the insurance not taken by
April), would be good to have but is not required — the payment may have been
dropped deliberately.

**Envelopes are a different model.** The README's virtual sub-accounts
earmark real money. Caps compare spending to an estimate and move no money.
The two stay separate.

## Directions rejected

- **A savings-target budget**: not the purpose.
- **Monthly-only caps**: yearly and irregular expenses make them noisy.
- **Amortising actuals across months**: distorts what the ledger says.
- **Expected-payment matching as a requirement**: budgets are estimates and an
  expense may be dropped.
- **Merging with envelopes**: different model, moves money.

## Open questions

- Where are caps entered: the same `$EDITOR` route as rules
  (`complex-classification-rules`), or commands?
- When does a period start: anchored to a date the user gives, or to calendar
  boundaries (a calendar year, a calendar month)?
- Does a cap change from some date onward, and how is the history of caps
  kept?
- Does unspent cap roll over into the next period?
- Does the report show only finished periods, the current one so far, or both?
- Is there a total cap across all expenses as well as per category?
- Which recurrence kinds are in the first version, and is RRULE the internal
  form shared with sampling?
