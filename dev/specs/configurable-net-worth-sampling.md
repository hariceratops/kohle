# Configurable net-worth sampling

## Overview

`net-worth-history` samples on two hard-coded dates per month: the 15th and
a period end chosen by `--period-end`, under the holidays of `--state` (or
the stored `state` setting). Salary days differ between employers (a fixed
day, the third Friday, the last working day), and none but the built-in two
can be expressed. Both the salary-day detection and the Bundesland change
which dates are sampled, and so they change the net-worth figures. The
Bundesland changes when the user moves. Today, a move re-samples every past
month under the new state's holidays. This feature replaces the hard-coded
dates with one stored list of labelled sampling rules, and turns the
Bundesland into an effective-dated history, so that a move applies from a
given date onward. The feature also fixes kohle's single recurrence
vocabulary. `budgeting` builds its period kinds on that vocabulary and must
not define a second one.

**Sample dates and price quotas.** Sample dates cost no API calls today.
`net-worth-history` only reads stored closes, taking the last one on or
before each date. `fetch-prices` asks for the latest close only, and
backfill is a non-goal of `price-fetcher-plugin`. Configurable sample dates
name the only past dates whose closes history needs. A future backfill can
therefore fetch just those dates within a provider's quota. This feature
does not build that backfill.

Personal-scale: the user is the only operator and consumer.

## Goals

- **Recurrence vocabulary.** One rule is one line of text. This spec fixes
  the syntax and meaning of every kind below. This feature builds the first
  five; `budgeting` builds the last two.

  | Rule | Meaning | Built here |
  |---|---|---|
  | `day N` | Calendar day N (1–31). It never moves. In a shorter month it is the last day. | yes |
  | `workday N` | Day N (clamped the same way), or the last working day before it. | yes |
  | `<nth> <weekday>` | `1st`–`4th` plus `mon`–`sun`, e.g. `3rd fri`. The nth such weekday of the month (the 3rd always falls on days 15–21). If that day is not a working day, the previous working day. | yes |
  | `last workday` | The last working day of the month. | yes |
  | `last day` | The calendar last day of the month. | yes |
  | `every N days\|weeks\|months from YYYY-MM-DD` | Every N units, anchored at the date. | `budgeting` |
  | `yearly MM-DD` | That calendar day every year. | `budgeting` |

  - A shift moves backward only. A shifted date may land in the previous
    month, and the row is dated where it lands.
  - **Working day** keeps its current meaning: Monday to Friday, not a
    public holiday of the Bundesland in force, and neither 24 nor 31
    December. The holidays used for a shift are those of the Bundesland in
    force on the rule's unshifted date.
- **Roles.** Every rule carries one role, and the set of roles is fixed:
  `mid-month` and `salary`. A rule list is written as
  `"<role>: <rule>; <role>: <rule>; …"`. The default list,
  `mid-month: day 15; salary: last workday`, reproduces today's
  `last-working-day` behaviour. This default is defined in one place in the
  code.
- **One rule list for the ledger.**
  - `set-sampling-rules "<rules>"` replaces the list as a whole.
  - The list applies to the whole history. Changing it re-samples every
    past month, and that is intended.
  - `list-sampling-rules` shows the current list.
- **The Bundesland is an effective-dated history.**
  - `move-state --from D XX` records the Bundesland from D onward.
    `--from` is required and takes a date or `start`, which means the entry
    that applies from the start of the ledger.
  - D may be in the future. Repeating an existing D replaces that entry;
    this is how a mistake is corrected. A later entry wins from its own
    date onward.
  - `list-states` shows the full history, oldest first, with `start` for
    the first entry.
- **All-or-nothing writes.** An invalid rule, role, date or state code
  writes nothing. The error names the bad part and lists the valid choices.
  Each successful change is one `Operation` in the audit trail. Reads leave
  no `OperationGroup` behind.
- **`net-worth-history`**
  - The sample dates are the dates the rule list produces within
    `--from`/`--to`. Then comes the final `--to` row, unless `--to` is
    already a sample date.
  - A new `role` column. A date reached by several rules is one row that
    lists every role (`mid-month, salary`).
  - The `--to` row that is not a sample date has an empty role.
  - **`--role mid-month|salary`** keeps rows that list that role. The
    `--to` row is always shown.
  - `--period-end` and `--state` are removed. The stored rule list and the
    Bundesland history are the only sources, and there is no per-run
    override.
  - A ledger with no Bundesland entry refuses and points to
    `move-state --from start <code>`.
  - No internal `month-end` or `BY` default remains anywhere.
- **`state` leaves the settings registry.** `set-setting state …` refuses
  and points to `move-state`, in the same way it refuses device keys.
- **`init`**
  - `init.toml`'s `state` stays required and becomes the `start` entry of
    the Bundesland history.
  - `init` also stores the default rule list. There is no `init.toml` key
    for rules.
  - On an existing database at head, `init` compares the file's `state`
    with the `start` entry. If they are equal, it reports "already
    initialized". If the entry differs or is missing, it exits non-zero and
    points to `move-state --from start`.
- **The migration** converts a stored `state` setting into the `start`
  entry, or creates no entry if it was unset. It also stores the default
  rule list.
- **Testable**
  - After `migrate` on a ledger with `state = BY`, `net-worth-history`'s
    dates and figures equal the pre-feature output of
    `--period-end last-working-day --state BY`. The only difference is the
    `role` column.
  - `move-state --from 2026-01-01 NI` on a `BY` ledger changes no row dated
    before 2026-01-01. The October 2025 `salary` row stays Friday 31
    October, which is a holiday in NI but not in BY. In 2028, the October
    `salary` row is Monday 30 October, because 31 October is Reformation
    Day in NI.
  - After `set-sampling-rules "salary: workday 25"`, every month in range,
    past ones included, has exactly one sample row (plus the `--to` row).
  - `day 15` on a Sunday stays on the 15th. `workday 15` on a Sunday moves
    to Friday the 13th.
  - `mid-month: day 15; salary: 3rd fri` in a month whose third Friday is
    the 15th yields one row with both roles.
  - An invalid rule in a list leaves `list-sampling-rules` output and the
    `operations` row count unchanged.
  - The `prices` row count and every price-plugin call are unchanged by
    every command this feature adds or changes.
  - Existing tests pass, apart from those that test the removed flags.
- **The README** documents the vocabulary, roles, the four commands, the
  `role` column, `--role`, and the removal of `--period-end` and `--state`.

## Non-Goals

- **Fetching past closes, backfill, or any change to `fetch-prices` or the
  price plugins.** `price-fetcher-plugin` stays as it is. Sample dates only
  prepare for a later backfill.
- **Thinning samples to fit a quota, or a sampling density per provider.**
  Quota spending stays in `fetch-prices`.
- **Rules that apply from a date.** There is one list for the whole
  history, and no sparse/dense split by period.
- **Building `every …` or `yearly`.** They are specified here and built by
  `budgeting`.
- **Raw RRULE input.** Any per-run override of the rules or the Bundesland.
- **User-defined role names.**
- **Any change to how a sample is valued.** A row is still `net-worth` as
  of its date.
- **Holiday calendars outside Germany**, and custom holiday lists.
- **Warnings when a Bundesland change shifts past samples.** Effective
  dating is the protection.
- **Renaming commands** (`cli-command-naming`) and any TUI.

## Technical Approach

- Python 3.12, SQLAlchemy 2.0, and a packaged Alembic migration. No new
  dependency beyond the pinned `holidays`. Whether RRULE, or a library such
  as `dateutil`, is the internal form is the architect's call. It must be
  able to carry the `budgeting` kinds without changing the user syntax.
- The rule list and the Bundesland history are ledger data. They live in
  the ledger and travel with snapshots. They are not device settings and
  must never go in `config.toml`.
- Writes go through `UnitOfWork` and `crud_create`. Parsing and validation
  return `Result` with domain error values.
- The working-day predicate stays one small function. It now takes the
  Bundesland in force for each date instead of a single state.
- `init.toml` validation no longer coincides with the `SETTINGS` registry,
  because `state` leaves it. The `state` code validator is shared by
  `init.toml` and `move-state`.
- Sample-date generation stays a pure function of the rule list, the
  Bundesland history and the range, with no price access. A later backfill
  can then call it to learn which dates need closes.

### Configuration-mechanism tension

`app-initialization` says no feature invents a further configuration
mechanism. This spec treats the Bundesland history (and the rule list) as
ledger data, like accounts, and not as a third configuration scope next to
the `settings` table and `config.toml`. The user has agreed to that reading.
Whether they share the `settings` table or get their own tables is left to
design. Either way, they must not become a general-purpose key/value
channel.

## Dependencies

**Two frozen specs contradict this one and must be amended by the user
before implementation.** No agent may edit `dev/specs/`. For each: unfreeze
it with `git mv dev/specs/<slug>.md dev/inbox/<slug>.md`, amend it (the user
can do this, or have `product-owner` do it while the file is in the inbox),
then refreeze it with `git mv` back.

1. **`app-initialization`**
   - `init.toml` keys are "checked with the same validator `set-setting`
     uses", and "`set-setting` does" change a setting. For `state`, this
     becomes the shared state-code validator and `move-state`.
   - `init` on an existing database at head "points to the setter". It now
     compares against the `start` entry and points to
     `move-state --from start`.
   - `set-setting` "the only key now is `state`". `state` is no longer a
     setting key.
   - "`net-worth-history` reads the stored Bundesland". `--state` is
     removed, not kept as an override. A missing Bundesland points to
     `move-state --from start <code>`, not `set-setting state`.
2. **`portfolio-and-profit-reporting`**
   - The `net-worth-history` sample dates, `--period-end`, and `--state`
     (with its `BY` default) are replaced by the stored rule list and the
     Bundesland history. "The 15th never moves" stays true as `day 15`.
   - The acceptance tests that use `--period-end` and `--state` are
     restated in terms of rules.
   - The Open Question "Persistent setting for `--state` and
     `--period-end`" is resolved by this spec.

## Open Questions

None blocking. Left to design:

- The storage shape of the rule list and the Bundesland history (see the
  tension above), and the internal recurrence form.
- The output layout of `list-sampling-rules` and `list-states`.
- Whether `list-settings` also shows the Bundesland in force today and the
  current rules.
