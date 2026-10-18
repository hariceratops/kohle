# Configurable sampling for net-worth-history

## Goal

Let the user choose when `net-worth-history` samples, and keep the choice from
being retyped on every run.

The problem behind it: sampling is fixed to the 15th plus one period end, and
the period end and Bundesland come only from `--period-end` (default
`last-working-day`) and `--state` (default `BY`). The portfolio-and-profit
spec left open whether these deserve a persistent setting and named it as the
architect's call; it was not decided.

## Considerations surfaced

**No configuration mechanism exists.** Persistent state is the database only;
environment variables are read only by price plugins; the market-value
precedent is "the flag is the only knob". A persistent setting means either a
settings table with a setter command, or `KOHLE_*` environment variables.

**Shared with initialization.** The Bundesland is exactly the kind of
mandatory configuration `app-initialization` lists. Deciding the mechanism
once, there, serves both; this brief is the first concrete consumer.

**Which days.** The 15th is a mid-month salary day for one case, and the
period end follows the last working day under a state's holidays. Another
user's pay day or reporting day differs, so the sample days themselves, not
only the state, may need to be configurable.

**Defaults disagree today.** `NetWorthHistory.execute` and `sample_dates`
default to `month-end` and `BY`, while the CLI defaults to `last-working-day`.
The CLI always passes both explicitly, so nothing is wrong now, but a
persistent setting should leave exactly one place defaults live.

## Directions rejected

None yet.

## Open questions

- Settings table, environment variables, or both?
- Is the setting only the state and period-end rule, or the list of sample
  days?
- Does a flag still override the stored value?
