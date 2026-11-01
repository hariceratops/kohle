# Savings targets

## Goal

Let the user set how much should go into a savings account per period, and
see where the money actually put in fell short of that target.

The problem behind it: `budgeting` catches overspending per expense category,
but its caps are not savings targets, and that was ruled out there on
purpose. Saving is still planned, and today a missed contribution is only
noticed by going looking for it.

Split out of `budgeting`, where it was a non-goal for v1. To revisit in 2027.

## Considerations surfaced

**Savings are assets, not unspent budget.** The user thinks of savings as
assets. So a target belongs on an asset account (a savings account, a virtual
sub-account, a depot), not on what is left of an expense cap. That is why
`budgeting` rejected "a savings-target budget": that model reads leftover
spending as saving.

**A contribution target is the mirror image of a cap.** A cap measures the
net spending on an expense account per period and reports overshoot. A
contribution target measures the net transfers into an asset account per
period and reports shortfall. The period and effective-dating machinery is
the same as `budgeting`'s: one target in force per account at a time, a
recurrence from the shared vocabulary, a change from a date D that cuts the
running period at D, and no rollover and no prorating. That machinery should
be reused, not copied.

**What counts as a contribution.** Net transfers in means money moved into
the account minus money taken out within the period. Market movement in a
depot is not a contribution: a price rise must not meet the target. This
depends on the ledger keeping transfers and valuation apart, which the
multi-unit model already does (lines carry their price at transaction time,
and prices fetched later are read only by reporting).

**Envelopes stay separate.** Earmarking money in a virtual sub-account is an
allocation that moves money. A target only compares contributions with a plan
and moves nothing. A target may sit on an envelope account, but neither
replaces the other.

## Directions rejected

- **Savings as the leftover of expense caps**: this is the model `budgeting`
  rejected. It ties saving to underspending rather than to money actually
  moved.
- **Counting market gains as contributions**: a target would then be met by
  the market rather than by saving.

## Open questions

- Whether targets share storage and commands with caps (one "plan" entry with
  a direction), or are a sibling with their own.
- Whether income transfers into the account count (interest, dividends
  reinvested), or only transfers from the user's own other accounts.
- Whether a target on a parent asset account covers its subtree, as a cap
  does.
- Whether the report is part of the budget report or a report of its own.
