# Budgeting

## Goal

Let the user set an intended amount per expense category and period, and see
how actual spending compares.

The problem behind it: kohle records and classifies what was spent but has no
notion of what was planned. `todo.md` lists "Budgetting" under categorization,
unstarted.

## Considerations surfaced

**Categories are accounts.** Expense categories are ordinary expense accounts
in the hierarchy, and a parent's balance is the sum of its children. A budget
on a parent category then naturally covers its subtree, and one on a leaf
covers the leaf.

**Actuals already exist.** `entries-in-period` and the balance machinery can
give spending per account over a period; a budget report is plausibly a pure
read joining planned amounts to those, in the same spirit as the other
reports.

**Where planned amounts live.** A budget is data that changes over time (a
different amount from some month on), so it is not a property of the account
row. Whether it is a new table keyed by account and period, and how a change
takes effect, is the design's call.

**Envelopes already exist.** The README describes virtual sub-accounts as
earmarked envelopes under a real account. Budgeting by planned amount and
budgeting by moving money into envelopes are different models; this brief
assumes the first and should confirm it.

**Dependency on classification.** Budget figures are only as good as the
classification behind them; see `strict-classification`.

## Directions rejected

None yet.

## Open questions

- Period: calendar month only, or arbitrary periods?
- Does unspent budget roll over?
- Is a budget per account only, or also a total across all expenses?
- What does the report flag: overspend only, or also unbudgeted categories
  that received spending?
- Is it a pure read like the other reports, with budgets set by a separate
  command?
