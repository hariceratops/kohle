# Configurable sampling for net-worth-history

## Goal

Let the user say on which days of the month `net-worth-history` samples, in
terms of how their salary actually arrives, and store that once instead of
retyping it on every run.

The problem behind it: sampling is fixed to the 15th plus one period end, and
the period end and Bundesland come only from `--period-end` (default
`last-working-day`) and `--state` (default `BY`). Salary days differ between
employers — a fixed day of the month, the third Friday, the last working
day — and none but the built-in two can be expressed. The
portfolio-and-profit spec left a persistent setting open as the architect's
call; it was never decided.

## Considerations surfaced

**Settings live in the ledger.** The mechanism is decided in
`app-initialization`: a settings table in the database, with the Bundesland
required at `init`. This feature is its first real consumer and should not
invent a second mechanism.

**A small rule vocabulary, not a calendar language.** Agreed direction: a
list of sampling rules, each one of three kinds:

- a fixed day of the month (the current 15th);
- the nth weekday of the month (third Friday);
- the last working day of the month (the current period end).

Today's behaviour becomes the default rule list rather than a special case
(inferred from the current code, to confirm in design).

**Holidays shift backward.** When a rule's day is a weekend or a holiday in
the configured Bundesland, the sample moves to the previous working day. A
third Friday on a holiday becomes the Thursday, which matches "the last
working day of the third week" whenever that week ends on a Friday.

**Defaults disagree today.** `NetWorthHistory.execute` and `sample_dates`
default to `month-end` and `BY`, while the CLI defaults to `last-working-day`.
The CLI always passes both explicitly, so nothing is wrong now; the stored
setting should leave exactly one place where defaults live.

**Ledgers without a Bundesland.** A ledger created before the settings table
has no state. `net-worth-history` refuses and points to the setter instead of
assuming `BY` (see `app-initialization`).

## Directions rejected

- **RFC 5545 RRULE strings**: they express all three kinds and more, but
  typing `FREQ=MONTHLY;BYDAY=+3FR` into a setter is a lot of syntax for one
  user with two or three rules.
- **Environment variables or flags as the only knob**: settings belong to the
  ledger (see `app-initialization`).
- **A fourth kind for "last working day of the nth week"**: covered by nth
  weekday plus the backward holiday shift, except for the definition question
  below.

## Open questions

- What is "the third week": days 15–21, or the third calendar week touching
  the month? It decides whether "third Friday" and "end of third week" differ.
- Does a flag still override the stored rules for a single run?
- Do two rules landing on the same date collapse to one sample?
- Is there one rule list for everything, or separate salary-day and
  period-end roles that reports treat differently?
