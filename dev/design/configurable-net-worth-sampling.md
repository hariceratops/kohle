# Design: Configurable net-worth sampling

Spec: `dev/specs/configurable-net-worth-sampling.md` (frozen). Issues:
`dev/issues/064`–`072`.

Abbreviations: **AI** is `dev/design/app-initialization.md`, **PP** is
`dev/design/portfolio-and-profit-reporting.md`, **DC** is
`dev/design/device-config.md`, **DT** is `dev/design/device-topology-and-sync.md`.

**Upstream state this design assumes.**

- The user is amending the frozen specs `app-initialization` and
  `portfolio-and-profit-reporting` to match this spec. §16 lists every
  sentence in their current text that conflicts with this design, including
  some the spec's Dependencies section does not name.
- The code and README still call the init file `init.rc`. The specs and DC
  call it `init.toml`, and DC §13 schedules the rename as a separate `change`.
  This design says `init.toml` throughout. §15 asks for that rename to land
  before 069.

---

## 1. Summary of the shape

| Concern | Decision | § |
|---|---|---|
| Where the rule list lives | Its own table, `sampling_rule_lists`, append-only. One row per list, in canonical user syntax. The highest id is in force. | 2 |
| Where the Bundesland history lives | Its own table, `state_entries`, with one row per effective date. `start` is stored as `date.min`, under `UNIQUE(effective_from)`. | 2 |
| Internal recurrence form | A closed sum type of frozen dataclasses, one per kind. No RRULE and no `dateutil`. Storage holds the user syntax, never the internal form. | 3 |
| Empty rule list | Refused. | 4 |
| `list-sampling-rules` | One line: the canonical list, byte-identical to what is stored and pasteable into `set-sampling-rules`. | 5.1 |
| `list-states` | A two-column table, `from` and `state`, oldest first, with `start` for the start entry. | 5.2 |
| `net-worth-history` `role` column | Last column. Roles are joined by `, `. The non-sample `--to` row renders `-`. | 5.3 |
| `list-settings` | Does not show the state or the rules. | 6 |
| Where the default list is defined | Only in the 064 migration, which seeds it into every ledger. `init` gets it by running that migration. | 8.2 |
| Modules | `recurrence.py` (the shared vocabulary), `sampling.py` (roles, lists, sample dates), `bundesland.py` (state codes and history). | 7 |
| Slice order | Fold 071 into 069. Land 070 right after 069. The `init.toml` rename goes before 069. | 15 |

New files:

| File | Contents | Slice |
|---|---|---|
| `kohle/use_cases/recurrence.py` | Rule kinds, `parse_recurrence`, `render_recurrence`, `occurrences`, `is_working_day` | 064, grows in 065–067 |
| `kohle/use_cases/bundesland.py` | `STATES` (moved), `validate_state`, `state_lookup`, `MoveState`, `ListStates` | 069, 070 |
| `kohle/services/sampling_services.py` | Rule-list services | 064, 065 |
| `kohle/services/state_services.py` | State-entry services | 069, 070 |
| `kohle/db/migrations/versions/<rev>_sampling_rule_lists.py` | Table, default seed, downgrade | 064 |
| `kohle/db/migrations/versions/<rev>_state_entries.py` | Table, conversion of the `state` setting, downgrade | 069 |
| `tests/test_recurrence.py`, `tests/test_bundesland.py`, `tests/test_sampling_cli.py` | See §18 | |

Changed: `kohle/use_cases/sampling.py` (rewritten), `reporting.py`,
`settings.py`, `ledger.py`, `kohle/domain/models.py`, `domain_errors.py`,
`kohle/db/schema.py` (`HEAD_REVISION`, twice), `kohle/app/cli/cli.py`,
`tests/conftest.py`, and the tests and README sections listed per slice in §15.

---

## 2. Decision 1: storage, and the configuration-mechanism tension

### 2.1 Two tables of their own, not the `settings` table

The spec reads the rule list and the Bundesland history as ledger data, like
accounts, and requires that neither becomes a general-purpose key/value
channel. **They get their own tables, each with a fixed, typed schema for
exactly one kind of fact.** Neither table has a key column, so nothing else
can be stored in either without a migration.

Why not the `settings` table:

- **The `settings` table is itself a key/value channel.** Putting non-settings
  into it under reserved keys is exactly how it would become the general
  channel the spec forbids. After this feature `SETTINGS` is empty (§9.6). The
  table would then hold only rows that are not settings.
- **The history needs a date per row and uniqueness per date.** A key/value
  row can only carry that by encoding the date into the key
  (`state@2026-01-01`), which is the channel abuse.
- **The rule list must stay out of `set-setting`, `list-settings` and
  `init.toml`** ("There is no `init.toml` key for rules"). Registering it in
  `SETTINGS` would give it all three: every registered key is required at
  init (AI §7.2).
- **Audit reads better.** `Operation.entity_type` is the table name, so
  `list-operations` says `state_entries` or `sampling_rule_lists`, not
  `settings`.

Both tables live in the ledger file, so `snapshot`, reader devices and the
Syncthing copy carry them with no change. Neither goes near `config.toml`.

### 2.2 `sampling_rule_lists`: append-only, one row per list

```python
class SamplingRuleList(base):
    """The ledger's sampling rules, as the canonical text set-sampling-rules
    takes. The row with the highest id applies to the whole history. Earlier
    rows are kept so the audit trail's creates still point at what was set;
    nothing reads them for sampling."""

    __tablename__ = "sampling_rule_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rules: Mapped[str] = mapped_column(String, nullable=False)
```

- **One row holds the whole list,** because the spec makes each successful
  change one `Operation`. A row per rule would make one replacement N deletes
  plus M creates (§14).
- **Append, never update.** `set-sampling-rules` creates a new row, so one
  `crud_create` is one `Operation`. The `create` points at a row that still
  holds the list as it was set. A list change re-samples every past month, so
  "what was the list before?" is the question the audit trail most needs to
  answer, and an in-place update would erase the answer.
- **This does not repeat the append-only settings design AI §15 rejected.**
  That was rejected because every read needed a max-per-key subquery. There
  is one list, so the read is `ORDER BY id DESC LIMIT 1`.
- **Append-only is also the simpler schema.** It needs no `CHECK (id = 1)`
  and no branch between create and update.
- **The text is the canonical user syntax** (§4.3), not the internal form.
  Kinds can be added (`budgeting`) or the internal form changed without a
  migration. The row is readable in `sqlite3`, and it is exactly what
  `list-sampling-rules` prints.
- **No `Archivable` and no `created_at`.** The `OperationGroup` already
  records when the change happened, and rows are never deleted.

### 2.3 `state_entries`: one row per effective date

```python
# The effective_from of the entry that applies from the start of the ledger.
START = date.min


class StateEntry(base):
    """The Bundesland from `effective_from` onward, until the next entry."""

    __tablename__ = "state_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (UniqueConstraint("effective_from", name="uq_state_entry_effective_from"),)
```

- **`start` is `date.min` (`0001-01-01`), not `NULL`.**
  - SQLite's `UNIQUE` treats NULLs as distinct, so a NULL `start` could be
    stored twice. With `date.min` there is one plain constraint over every
    entry, `start` included.
  - "In force on D" becomes "the latest `effective_from` ≤ D", with no special
    case. `start` sorts first in SQL and in Python.
  - The sentinel appears in exactly two places: `move-state --from start`
    parses to it, and `list-states` renders it as `start`.
  - `--from 0001-01-01` aliases `start`. The two mean the same thing, so this
    needs no guard.
- **`START` sits in `models.py` beside the model,** as `DEFAULT_RULE_PRIORITY`
  sits beside `Rule`.
- **Replacing an existing D updates the row in place** (`crud_update`, one
  `Operation`). This follows `set_setting_service` and
  `set_price_binding_service`. The old state of a corrected entry is not kept,
  the same as for every other update in the codebase (AI §7.5; that belongs to
  `undo-delete-edit`).
- **There is no delete.** The spec gives no removal. §17 item 6 records the
  consequence.
- **Codes are stored as the two-letter string,** as the `state` setting was.

---

## 3. Decision 2: the internal recurrence form

### 3.1 A closed sum type, one frozen dataclass per kind

```python
@dataclass(frozen=True, slots=True)
class Day:            # day N
    day: int

@dataclass(frozen=True, slots=True)
class Workday:        # workday N                                   (066)
    day: int

@dataclass(frozen=True, slots=True)
class NthWeekday:     # <nth> <weekday>; nth 1-4, weekday 0=mon … 6=sun (067)
    nth: int
    weekday: int

@dataclass(frozen=True, slots=True)
class LastWorkday:    # last workday
    pass

@dataclass(frozen=True, slots=True)
class LastDay:        # last day                                    (065)
    pass

Recurrence = Day | Workday | NthWeekday | LastWorkday | LastDay
```

`budgeting` adds `Every(n: int, unit: Literal["days", "weeks", "months"],
anchor: date)` and `Yearly(month: int, day: int)`, then adds a parse production
and an `_unshifted` case for each. The user syntax, the storage and every other
caller stay as they are.

The kinds map one-to-one onto the rows of the spec's table. Each consumer
dispatches with a `match` that ends in `assert_never`, which is already the
codebase's pattern (`reporting._market_value`):

- **`render_recurrence`** must return exactly what the user wrote. Folding
  `last day` into `Day(31)` would make `list-sampling-rules` print `day 31`.
- **Whether a kind shifts.** `Workday`, `NthWeekday` and `LastWorkday` shift
  back to a working day. `Day` and `LastDay` never move, and neither do
  `Every` or `Yearly`.
- **The unshifted date.**

### 3.2 Why not RRULE (`dateutil.rrule`)

`python-dateutil` is already pinned, so this is a judgement of fit, not of
cost. It was rejected for four reasons:

1. **RRULE has no notion of a holiday calendar.** `workday N`, `<nth>
   <weekday>` and `last workday` move to the previous working day under the
   Bundesland in force on each unshifted date. That has to be post-processing
   whatever generates the dates, so RRULE would carry only the trivial part.
2. **RFC 5545 drops invalid dates; the spec clamps.** `BYMONTHDAY=31` skips
   30-day months, but `day 31` must give the last day. RRULE can express the
   clamp only through `BYMONTHDAY=28,29,30,31;BYSETPOS=-1`-style tricks that
   hide what the rule means. The same mismatch returns for `every 1 months
   from 2026-01-31` and `yearly 02-29` (§17 item 9).
3. **A rule would still need our own type around it.** Rendering back to the
   user syntax and the "does it shift" flag do not fit in an RRULE string, so
   the RRULE would be a third syntax, next to the user syntax and the Python
   values, kept consistent by hand.
4. **The arithmetic is a few lines per kind** with `calendar.monthrange` and
   `timedelta`, and raw RRULE input is a spec non-goal.

### 3.3 The generation interface is a date range, not a month

```python
def occurrences(
    rule: Recurrence, start: date, end: date, state_on: Callable[[date], str]
) -> list[date]:
    """Every date the rule lands on in [start, end], ascending: each unshifted
    date, moved back to a working day under the state in force on that
    unshifted date when the kind shifts."""
```

- **A range is forced by `budgeting`.** `every N days from D` has no "date in
  month M".
- **Month-based kinds walk from `start`'s month through the month after
  `end`'s.** A shift moves backward only, so next month's date can land inside
  the range. Example: with `--to 2026-04-30`, `1st fri` of May 2026 is Friday
  1 May, a holiday, and it lands on Thursday 30 April. A shift moves at most 5
  days, measured with holidays 0.106 for 2020–2040 in BY and NI (the longest:
  Sunday 2025-12-28 back to Tuesday 12-23). So one extra month is enough, and
  the shift loop needs no guard, as `period_end` needs none today (PP §6.1).
- **The state comes from `state_on(unshifted)`, and only for kinds that
  shift.** That implements the spec's "the holidays used for a shift are those
  of the Bundesland in force on the rule's unshifted date". It also means a
  list of non-shifting kinds never imports `holidays` (§7.1).
- **The unshifted dates.**
  - `Day(n)` and `Workday(n)` give `min(n, last day of month)`.
  - `LastDay` and `LastWorkday` give the last day of the month.
  - `NthWeekday(nth, wd)` gives day `1 + (wd − first.weekday()) % 7 + 7·(nth − 1)`.
    That is at most day 28, so it never needs clamping.

### 3.4 The working-day predicate

```python
def is_working_day(day: date, state: str) -> bool:
    return day.weekday() < 5 and day not in _public_holidays(state) and (day.month, day.day) not in {(12, 24), (12, 31)}

@functools.cache
def _public_holidays(state: str) -> "holidays.HolidayBase":
    # Imported here: it costs ~0.19 s, which every other command would pay.
    import holidays
    return holidays.country_holidays("DE", subdiv=state)
```

This is the spec's "one small function", which "now takes the Bundesland in
force for each date". Today's closure, `working_days(state)`, built one
calendar per report. With several states per report, it becomes a cache keyed
by state. That cache is bounded at 16 entries and lives as long as the
process, which is right for a CLI. §13 covers its thread-safety for the TUI.

---

## 4. Decision 3: the rule-list syntax; an empty list is refused

### 4.1 Grammar

```
list   := item (";" item)*          blank items are skipped
item   := role ":" rule
role   := "mid-month" | "salary"
rule   := "day" N | "workday" N | ORD WD | "last" "workday" | "last" "day"
N      := 1..31 in decimal digits
ORD    := "1st" | "2nd" | "3rd" | "4th"
WD     := "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun"
```

- **The parser matches tokens.** It splits items on `;`, partitions each on
  the first `:`, and runs `match rule_text.split():` over the cases. Whitespace
  runs are therefore insignificant (`salary:last  workday` is accepted).
- **Matching is case-sensitive and lowercase,** like `STATES`, so each kind
  has one spelling, and stored and listed text equal what the spec documents.
- **Blank items are skipped,** so a trailing `;` is harmless.
- **A role may repeat** (two employers: `salary: last workday; salary: workday
  15`). Items keep their order, and duplicates are kept as typed. Duplicates
  are harmless because samples are merged by date (§7.2).
- **The first bad item stops the parse,** as `validate_settings` stops at the
  first bad key.
- **The kinds named in "valid choices" grow per slice.** 064 accepts only
  `day N` and `last workday`. Before `budgeting` builds them, `every …` and
  `yearly …` are "invalid rule", listing the built kinds (§17 item 8).

### 4.2 An empty list is refused

`set-sampling-rules ""` and `set-sampling-rules ";"` return
`EmptySamplingRules`. Three reasons:

- An empty list leaves `net-worth-history` with only the `--to` row, which is
  `net-worth` with an extra step. No user wants that.
- An empty argument is more likely a shell quoting slip (`"$RULES"` with
  `RULES` unset) than a wish.
- Refusing it removes a state that `list-sampling-rules`, the history and a
  future backfill would each have to handle.

A list without one of the roles is fine. `salary: workday 25` alone is the
spec's own example.

### 4.3 Canonical text

`render_sampling_rules` joins `f"{role.value}: {render_recurrence(r)}"` with
`"; "`. `render_recurrence` gives `day 15`, `workday 25`, `3rd fri`,
`last workday` and `last day`, with N as a plain integer (`day 05` → `day 5`).
Parsing then rendering is the identity on canonical text. The default,
`mid-month: day 15; salary: last workday`, is canonical.

---

## 5. Decision 4: output layouts

### 5.1 `list-sampling-rules`

It prints the stored text on one line and nothing else:

```
mid-month: day 15; salary: last workday
```

- **The list is replaced only as a whole,** so the unit the user edits is the
  whole string. A table would have to be joined back by hand, which is a
  needless chance for a typo. The output is byte-identical to the stored row
  and to what `set-sampling-rules` accepts. To edit: copy, change one item,
  `kohle-cli set-sampling-rules "…"`.
- **It prints the stored text without re-parsing,** because the setter only
  ever stores canonical text (§9.1).

`set-sampling-rules` confirms with `Set sampling rules to <canonical>`, both
after a change and after an identical no-op, as `set-setting` does.

### 5.2 `list-states`

It prints a tabulate table in the `list-rules` style:

```
from        state
----------  -------
start       BY
2026-01-01  NI
```

- **Oldest first, with `start` for `START`,** as the spec asks. Each row reads
  as the `move-state --from <from> <state>` that recorded it.
- **There is no "in force today" marker.** It would make a pure listing of
  ledger data depend on the clock. Dates make the answer obvious, a future
  entry included.
- **An empty history** prints
  ``No state recorded; run `kohle-cli move-state --from start <code>` ``,
  exit 0. The "No rules" precedent, plus the pointer the refusal in
  `net-worth-history` gives.
- **A history whose first entry is dated** (§9.4) lists that date first. No
  `start` row is invented.

`move-state` confirms with `Set state from start to BY`, or
`Set state from 2026-01-01 to NI`.

### 5.3 `net-worth-history`

```
date          at cost    at market  estimated    role
----------  ---------  -----------  -----------  -----------------
2026-05-15   10210.00     10294.50  1 of 3       mid-month, salary
2026-05-29   12890.00     12961.20  1 of 3       salary
2026-06-15   12650.00     12702.00  2 of 3       mid-month
2026-06-20   12655.00     12709.00  1 of 3       -
```

- **`role` is the last column.** Its values contain spaces
  (`mid-month, salary`). Last, they cannot move the date and money columns for
  a whitespace-split consumer such as `awk` or the tests' `split()`, and the
  equivalence test can compare `split()[:6]` with the pre-feature output
  directly (§18.4).
- **Roles appear in `Role` declaration order,** `mid-month` before `salary`,
  without duplicates. That is the spec's `mid-month, salary`.
- **The non-sample `--to` row's role is `None`,** which renders `-` under the
  existing `missingval="-"` convention. This is how this design reads the
  spec's "empty role" (§17 item 1).

---

## 6. Decision 5: `list-settings` shows neither the state nor the rules

`list-settings` keeps listing only `SETTINGS` keys (none after 069), then the
ledger path and revision. Four reasons:

- **They are not settings.** The spec takes `state` out of the registry and
  makes `set-setting state` refuse. Listing it under settings invites exactly
  that command.
- **`list-settings` lines are `key = value`, made to paste into the init file**
  (AI §2). Neither would paste correctly. The state "in force today" differs
  from the `start` entry `init` compares against after any move, and
  `init.toml` has no rules key.
- **"In force today" would add a clock dependency** to a listing that is
  otherwise pure ledger data.
- **Each has its own listing command,** named in the README beside
  `list-settings`.

With an empty registry, `list_settings_cmd` prints the blank separator only
when there are keys, so the output starts at `ledger:`.

---

## 7. Modules

### 7.1 `kohle/use_cases/recurrence.py`: the shared vocabulary, pure

```python
Recurrence = Day | Workday | NthWeekday | LastWorkday | LastDay       # §3.1
KINDS: tuple[str, ...]          # syntax of the built kinds, in spec-table order, for error messages

def parse_recurrence(text: str) -> Result[Recurrence, InvalidRecurrence]
def render_recurrence(rule: Recurrence) -> str
def occurrences(rule: Recurrence, start: date, end: date, state_on: Callable[[date], str]) -> list[date]
def is_working_day(day: date, state: str) -> bool
```

- **It knows nothing of roles, storage, or how the history is stored.** It is
  given a `state_on` function. `budgeting` imports this module and no other
  sampling code.
- **No DB and no prices.** The price guard is extended to it (§18.6).
- **`holidays` is imported lazily** inside `_public_holidays`, so a rule list
  with only `day` and `last day` kinds never imports it. That is the
  generalisation of today's "never imported under `month-end`".

### 7.2 `kohle/use_cases/sampling.py`: roles, rule lists, sample dates

```python
class Role(Enum):
    mid_month = "mid-month"
    salary = "salary"

@dataclass(frozen=True, slots=True)
class SamplingRule:
    role: Role
    recurrence: Recurrence

@dataclass(frozen=True, slots=True)
class Sample:
    on: date
    roles: tuple[Role, ...]      # Role order; () only for the --to row that no rule reached

def parse_sampling_rules(text: str) -> Result[list[SamplingRule], SamplingRulesError]
def render_sampling_rules(rules: Sequence[SamplingRule]) -> str

def sample_dates(
    rules: Sequence[SamplingRule], state_on: Callable[[date], str], start: date, end: date
) -> list[Sample]:
    """Every date a rule lands on in [start, end], one Sample per date with
    every role that reached it, ascending; then `end` with no role unless it
    is already the last date. No price access: a backfill can call this to
    learn which dates need closes."""

def current_sampling_rules(ctx: DbTransactionContext) -> Result[list[SamplingRule], SamplingRulesError]

class SetSamplingRules(UnitOfWork[str, SamplingRulesError]):     # 065
    def execute(self, text: str) -> Result[str, SamplingRulesError]   # Ok(canonical text)

class ListSamplingRules(UnitOfWork[str, SamplingError]):         # 065
    def execute(self) -> Result[str, SamplingError]
```

- **`sample_dates` is total; it returns no `Result`.** The only refusal (no
  `start` entry) belongs to the history and happens in `state_lookup` (§7.3)
  before `sample_dates` is called. So "pure function of the rule list, the
  Bundesland history and the range" holds, with the history given in function
  form.
- **Samples merge by date** into a `dict[date, set[Role]]`. The result is
  sorted, so the dates are ascending, as `aggregate_by_unit_through` requires.
- **The `--to` row is part of `sample_dates`, as it is today.** A backfill
  needs a close for it too.
- **`current_sampling_rules(ctx)`** reads the stored text and parses it. It is
  shared by `NetWorthHistory` and nothing else; `ListSamplingRules` prints the
  stored text without parsing it. A stored text that fails to parse can only
  come from a hand-edited database. Its `Err` propagates like any other.
- **Removed:** `PeriodEnd`, `period_end`, `working_days`, and the `"BY"` and
  `month_end` defaults (064). `STATES` moves to `bundesland.py` in 069.

### 7.3 `kohle/use_cases/bundesland.py`: codes and the history

```python
STATES = ("BB", "BE", "BW", "BY", "HB", "HE", "HH", "MV",
          "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH")          # moved from sampling.py, comment kept

def validate_state(value: object) -> Result[str, InvalidState]      # shared: init.toml and move-state

def state_lookup(entries: Sequence[StateEntry]) -> Result[Callable[[date], str], NoStartState]:
    """`entries` oldest first, as list_state_entries_service returns them.
    Err unless the first entry is START, so the lookup is total."""

class MoveState(UnitOfWork[StateEntry, StateError]):                # 070
    def execute(self, effective_from: date, state: object) -> Result[StateEntry, StateError]

class ListStates(UnitOfWork[list[StateEntry], StateError]):         # 069
    def execute(self) -> Result[list[StateEntry], StateError]
```

- **`state_lookup`** collects the `effective_from` values into a list and
  returns `lambda day: entries[bisect_right(froms, day) - 1].state`. D itself
  is covered: `move-state --from 2026-01-01 NI` applies on 1 January. A future
  D is ordinary.
- **`validate_state` takes `object`,** as AI §7.2's validators do, so TOML's
  `state = 1` fails with the same message as `state = "XX"`.
- **It is a module of its own, not part of `sampling.py`,** because `init`
  (`ledger.py`) and later `budgeting` (through the `workday` kinds) consume the
  history without needing roles.
- **The pure functions take `StateEntry` ORM rows,** as
  `aggregate_by_unit_through` takes `JournalLine` rows. Tests build transient
  `StateEntry(effective_from=…, state=…)` objects, as `test_sampling.py`
  builds lines. No value-type copy is added.

---

## 8. Models, migrations, services

### 8.1 Models

`SamplingRuleList` (§2.2), `StateEntry` and `START` (§2.3), in
`kohle/domain/models.py`.

### 8.2 Migration 064, `<rev>_sampling_rule_lists.py` (revises `e5a1c3b7d902`)

```python
# The default rule list, which reproduces the pre-feature
# `--period-end last-working-day`. Seeded into every ledger here; init gets it
# by running this migration.
DEFAULT_SAMPLING_RULES = "mid-month: day 15; salary: last workday"
```

- **Upgrade** runs `create_table` and then
  `INSERT INTO sampling_rule_lists (rules) VALUES (:default)`. The insert is
  unconditional, so a fresh `init` and a `migrate` of an old ledger both end
  with the default. This is the People-root precedent (`d4a2e6f0b917`): a
  migration seeds what every ledger at head must have.
- **The default is defined here and nowhere else in `kohle/`.**
  - The migration is its only writer: `init` runs every migration, and no
    other code needs the default.
  - That satisfies the spec's "defined in one place in the code" and keeps the
    version script self-contained. Importing app code would be a first for a
    version script, so a later edit to an app constant would silently change
    what this old migration writes.
  - Tests restate the spec's literal (§18.1), as tests restate any spec value.
- **Seeds record no `Operation`.** No migration does (People root).
- **Downgrade** refuses unless the table holds exactly one row equal to
  `DEFAULT_SAMPLING_RULES`. The previous schema behaved as the default does,
  so that table is representable. Any other content is a user declaration the
  previous schema cannot hold (`_refuse_if_unrepresentable`, as for settings).
  Otherwise it runs `drop_table`.
- **`HEAD_REVISION`** in `kohle/db/schema.py` takes the new revision.
  `test_schema_check` pins it.

### 8.3 Migration 069, `<rev>_state_entries.py` (revises 064's)

- **Upgrade:**
  1. `create_table('state_entries', …, UniqueConstraint('effective_from'))`.
  2. `INSERT INTO state_entries (effective_from, state) SELECT '0001-01-01', value FROM settings WHERE key = 'state'`.
     This is the spec's "converts a stored `state` setting into the `start`
     entry, or creates no entry if it was unset". `'0001-01-01'` is how
     SQLAlchemy's SQLite `Date` stores `date.min`; §18.5 pins that by reading
     it back through the model.
  3. `DELETE FROM settings WHERE key = 'state'`. `state` leaves the registry,
     and a left-over row would be an orphan that `ListSettings` ignores and
     that would contradict the history after the first move.
- **Downgrade:**
  1. Refuse if any entry has `effective_from <> '0001-01-01'`. A move cannot
     be held by one setting.
  2. `INSERT INTO settings (key, value) SELECT 'state', state FROM state_entries WHERE effective_from = '0001-01-01'`.
  3. `drop_table('state_entries')`.
  So a ledger whose history is only a `start` entry round-trips to
  `state = <code>`.
- **`HEAD_REVISION`** is bumped again.
- **Dangling audit references.** The `Operation` that created the deleted
  `settings` row stays, pointing at a row that no longer exists. That is
  historically true and harmless, because `Operation.entity_id` has no foreign
  key. The same holds for `state_entries` operations after a downgrade.

### 8.4 `kohle/services/sampling_services.py`

```python
@crud_retrieve
def current_rule_list_service(ctx) -> Result[SamplingRuleList, SamplingError]:
    # highest id, .one(): every ledger at head has a row (§8.2), and so does every test schema (§18.1)

@crud_create
def _add_rule_list_service(ctx, rules: str) -> Result[SamplingRuleList, SamplingError]

def set_rule_list_service(ctx, rules: str) -> Result[SamplingRuleList, SamplingError]:
    """Append `rules` as the current list. The current text writes nothing, so a
    replay leaves no OperationGroup."""
```

### 8.5 `kohle/services/state_services.py`

These mirror `setting_services.py` one for one:

```python
@crud_retrieve
def list_state_entries_service(ctx) -> Result[list[StateEntry], StateError]   # ORDER BY effective_from

@crud_create
def _create_state_entry_service(ctx, effective_from: date, state: str) -> Result[StateEntry, StateError]

@crud_update
def _update_state_entry_service(ctx, entry_id: int, state: str) -> Result[StateEntry, StateError]

def put_state_entry_service(ctx, effective_from: date, state: str) -> Result[StateEntry, StateError]:
    """Create the entry for `effective_from`, or replace its state. The same
    state writes nothing."""
```

Infrastructure errors map to `SamplingError(str(err))` and
`StateError(str(err))`, as `SettingError` does in `setting_services.py`.

---

## 9. Use cases

### 9.1 `SetSamplingRules` (065)

1. `parse_sampling_rules(text)` runs before the transaction. On `Err`, it
   returns the error and nothing is opened, the same order as `SetSettings`.
2. `canonical = render_sampling_rules(rules)`.
3. Inside `_run`: `set_rule_list_service(ctx, canonical)`.
4. It returns `Ok(canonical)`.

An invalid list writes nothing and leaves `list-sampling-rules` and the
`operations` count unchanged (spec testable).

### 9.2 `ListSamplingRules` (065)

It reads `current_rule_list_service(ctx)` and returns `.rules`. It reads only,
so it leaves no group.

### 9.3 `MoveState` (070) and `ListStates` (069)

- **`MoveState.execute(effective_from, state)`** runs `validate_state(state)`
  before the transaction, then `put_state_entry_service`.
  - The date reaches it already parsed (§10.2).
  - An identical entry records nothing.
  - A changed D records one `update`; a new D records one `create`.
- **`ListStates`** wraps `list_state_entries_service`.

### 9.4 `NetWorthHistory` (`reporting.py`)

```python
@dataclass(frozen=True, slots=True)
class HistoryRow:
    on: date
    roles: tuple[Role, ...]
    report: ValuedNetWorthReport

class NetWorthHistory(UnitOfWork[list[HistoryRow], HistoryError]):
    def execute(self, start: date | None, end: date, max_age_days: int,
                role: Role | None = None) -> Result[list[HistoryRow], HistoryError]
```

Inside one `_run`:

1. `current_sampling_rules(ctx)`.
2. `list_state_entries_service(ctx)`, then `state_lookup(entries)`. A missing
   `start` entry gives `Err(NoStartState())`.
3. `net_worth_lines(ctx)`, and the default start date as today.
4. `sample_dates(rules, lookup, first_day, end)`.
5. With `role` given, keep a sample if `role in s.roles or s.on == end`.
6. The rest is unchanged: `aggregate_by_unit_through` over `[s.on for s in
   samples]`, then `valued_net_worth` per date.

- **The use case reads the rules and the states itself.** AI §15 deferred
  this move ("can move the resolution inward then"), and with no per-run
  override nothing needs to happen in the CLI. Everything then goes through one
  `UnitOfWork`, and the history no longer opens a second session for settings.
- **The refusal is unconditional,** even for a rule list that never shifts.
  The spec says so ("A ledger with no Bundesland entry refuses"), and it
  matches AI §17 item 2.
- **A history with dated entries but no `start` entry also refuses.** This
  follows issue 069 ("no `start` entry"). The spec's wording, "no Bundesland
  entry", is the subset of that case with no entries at all. Without a `start`
  entry, the state before the first date is undefined (§14, §17 item 5).
- **`--role` filters before valuation,** so excluded rows cost no close reads,
  and a later TUI gets the filter for free.
  - The row dated `--to` is always kept, even when it is a sample date for the
    other role, so "where I stand at `--to`" never disappears on the 15th
    (§17 item 2).
  - Dropping dates does not change any other date's figures, because the fold
    is over a prefix.
- **Interim signatures.**
  - 064 adds no `role`, and takes `state: str` from the CLI, built into
    `lambda _: state`.
  - 068 adds `role`.
  - 069 drops `state`.

### 9.5 `init` (`ledger.py`)

```python
@dataclass(frozen=True, slots=True)
class InitFile:
    state: str
    settings: dict[str, str]          # SETTINGS keys; none today

def validate_init_file(raw: Mapping[str, object]) -> Result[InitFile, InitFileError]:
    # In file order: `state` -> validate_state; a SETTINGS key -> its validator;
    # anything else -> UnknownInitKey(key, ["state", *SETTINGS]).
    # Then MissingInitKeys for `state` or any SETTINGS key absent (unknown before
    # missing, as now).

class PopulateLedger(UnitOfWork[None, InitError]):
    def execute(self, init: InitFile) -> Result[None, InitError]:
        # one transaction: put_state_entry_service(ctx, START, init.state), then
        # set_setting_service per init.settings item

def init_ledger(path: Path, init: InitFile) -> Result[Initialized, InitError]
```

- **`validate_init_file` replaces `validate_init_settings`.** That is the
  spec's "init.toml validation no longer coincides with the SETTINGS registry".
  The `state` validator is `validate_state`, shared with `move-state`.
- **`PopulateLedger`** is `build_ledger`'s `populate` hook. It writes the
  `start` entry and the settings in one transaction, so `init` keeps one
  `OperationGroup`, the property AI §7.4 gave `SetSettings` for the same
  reason. It does not write the rule list: the 064 migration that
  `build_ledger` just ran has seeded it (§8.2). `init` remains all-or-nothing
  by staging.
- **`_compare_existing(path, init)`,** which is 071 folded into 069:
  1. `check_schema`, as today.
  2. `ListStates`, then find the `START` entry.
  3. Missing, or `state != init.state`, gives
     `Err(StartStateDiffers(path, stored, init.state))`.
  4. Then the `SETTINGS` comparison, unchanged: `SettingDiffers`, with no keys
     today.
  It reads only. It compares with the `start` entry, never with the state in
  force today.

### 9.6 `settings.py` after 069

- `_bundesland` and `validate_init_settings` are removed.
- `SETTINGS: dict[str, Validator] = {}`. Its comment changes to: "Ledger
  settings, in listing order. `init.toml` accepts `state` (bundesland.py) plus
  these."
- `ListSettings` and `SetSettings` are unchanged.
- `UnknownSetting` with no known keys renders `unknown setting 'foo'; there
  are no ledger settings`.
- After this feature `set-setting` accepts no key until a later feature adds
  one (§17 item 10).

---

## 10. CLI (`kohle/app/cli/cli.py`)

### 10.1 New commands

| Command | Arguments | `writes` | Output |
|---|---|---|---|
| `set-sampling-rules` | `RULES` (one argument) | `True` | `Set sampling rules to <canonical>` |
| `list-sampling-rules` | | `False` | §5.1 |
| `move-state` | `--from start\|YYYY-MM-DD` (required), `STATE` | `True` | `Set state from <from> to <code>` |
| `list-states` | | `False` | §5.2 |

Every new command declares `writes`, so the reader refusal applies to the two
writers before their bodies run (DT).

### 10.2 `--from` for `move-state`

`EffectiveFromType(click.ParamType)` follows `DecimalParamType`.

- `"start"` gives `START`.
- Otherwise `datetime.strptime(value, "%Y-%m-%d").date()`, the same strict
  format as every other date option, and not `date.fromisoformat`, which
  accepts `20260101` and week dates.
- Anything else fails with `self.fail(f"{value!r} is not start or a date
  YYYY-MM-DD")`, a usage error with exit 2 that opens no session.

`STATE` is a plain argument, not `click.Choice`: the code goes through the
shared `validate_state` and gets the same `InvalidState` text as `init.toml`.
This is AI §10's reason for `set-setting KEY`.

### 10.3 `net-worth-history`

- **064:** `--period-end` and the `PeriodEnd` import go. The `role` column is
  added (§5.3). `--state` stays, with its stored-setting fallback.
- **068:** `--role` with `type=click.Choice([r.value for r in Role])` and
  default `None`. An unknown value is a usage error that lists the choices
  (issue 068) and opens no session. Help text: "Only rows sampled for this
  role; the row dated --to is always shown".
- **069:** `--state`, the `ListSettings` read and `StateNotSet` go. The command
  calls `NetWorthHistory(make_session()).execute(start, end, max_age_days,
  role)` and maps `Err` to `ClickException`.
- Rows: `"role": ", ".join(r.value for r in row.roles) or None`, appended
  after `estimated`.

### 10.4 `set-setting` (069)

After the device-key check, `if key == "state": raise
click.ClickException(str(StateNotASetting()))`. The spec says this refusal
works "in the same way it refuses device keys". Both are a CLI redirect of a
real key that is not a ledger setting. It exits 1 and writes nothing.

### 10.5 `init` (069)

It calls `validate_init_file` in place of `validate_init_settings`, and still
prefixes errors with the file path. It calls `init_ledger(ledger_path(config),
init_file)`.

---

## 11. Errors (`kohle/domain/domain_errors.py`)

| Class | Fields | Message | Slice |
|---|---|---|---|
| `RecurrenceError(Exception)` | | base | 064 |
| `InvalidRecurrence(RecurrenceError)` | `text, expected` | `invalid rule {text!r}; expected {expected}` | 064 |
| `SamplingError(Exception)` | | base; also wraps infrastructure failures | 064 |
| `EmptySamplingRules(SamplingError)` | | `no sampling rules given; write "<role>: <rule>; …" with roles mid-month, salary` | 064 |
| `InvalidRole(SamplingError)` | `item, role: str \| None` | `None`: `{item!r} has no role; write "<role>: <rule>" with role mid-month or salary`. Otherwise: `unknown role {role!r} in {item!r}; roles: mid-month, salary` | 064 |
| `StateError(Exception)` | | base; also wraps infrastructure failures | 069 |
| `InvalidState(StateError)` | `value, valid` | `invalid state {value!r}; expected one of {", ".join(valid)}` (today's text, so existing assertions on `expected one of …` hold) | 069 |
| `NoStartState(StateError)` | | ``no state from the start of the ledger; record it with `kohle-cli move-state --from start <code>` `` | 069 |
| `StartStateDiffers(StateError)` | `path, stored: str \| None, wanted` | `None`: ``ledger at {path} has no state from the start; record it with `kohle-cli move-state --from start {wanted}` ``. Otherwise: ``ledger at {path} has state {stored} from the start but init.toml says {wanted}; init never changes an existing ledger, `kohle-cli move-state --from start {wanted}` does`` | 069 |
| `StateNotASetting(SettingError)` | | ``state is not a setting; record a move with `kohle-cli move-state --from <start|YYYY-MM-DD> <code>` `` | 069 |
| `InitFileError(Exception)` | | base | 069 |
| `UnknownInitKey(InitFileError)` | `key, known` | `unknown key {key!r}; known keys: {", ".join(known)}` | 069 |
| `MissingInitKeys(InitFileError)` | `keys` | `missing {", ".join(keys)}` | 069 |

**`expected` text for `InvalidRecurrence`,** naming the bad part and the valid
choices:

| Bad part | `expected` |
|---|---|
| Unknown kind | `one of: ` + `", ".join(KINDS)` |
| N out of range or not digits | `day N with N from 1 to 31` (or `workday N`) |
| `last <x>` | `last workday or last day; for a weekday use 1st, 2nd, 3rd or 4th` |
| Second token a weekday, first not an ordinal (`5th fri`, `first fri`) | `an ordinal 1st, 2nd, 3rd or 4th before the weekday` |
| First token an ordinal, second not a weekday | `a weekday mon, tue, wed, thu, fri, sat or sun` |

**Unions:**

- `SamplingRulesError = SamplingError | InvalidRecurrence`
- `HistoryError = ValuationError | SamplingRulesError | StateError`
- `InitError = LedgerError | SettingError | StateError` (+`InitFileError` at
  the CLI seam)

**Removed:** `StateNotSet` and `MissingSettings` (069). `SettingDiffers` stays
for future `SETTINGS` keys. Its `init.rc says` wording goes with the rename
`change`.

---

## 12. README and AGENTS.md

### 12.1 README sections

| Section | Change | Slice |
|---|---|---|
| Net worth over time | Remove the `--period-end` sentences. | 064 |
| Net worth over time | Remove `--state` and `set-setting state`. | 069 |
| Net worth over time | Full rewrite (072): the vocabulary table, with all seven kinds and `every`/`yearly` marked "specified, built by budgeting"; shifts; working day; the Bundesland in force on the unshifted date; roles; the default list; `set-sampling-rules`; `list-sampling-rules`; the `role` column; `--role` and the always-shown `--to` row; the removal of `--period-end` and `--state`; sample dates cost no API calls and backfill is not built. | 064, 069, 072 |
| New "Bundesland" subsection | `move-state --from start\|D`, replace-by-repeating, future dates, `list-states`, no per-run override. | 072 |
| Where the ledger lives | The one-time move becomes `migrate`, then `move-state --from start <code>` if the old ledger had no state. | 069 |
| Device config | The "two scopes" paragraph: ledger settings (none yet) are in `settings`. The Bundesland history and the sampling rules are ledger data with their own commands. Both travel with the ledger. | 069 |
| First run | `state` becomes the `start` entry. `list-states` replaces `list-settings` in the example. The existing-ledger pointer becomes `move-state --from start`. `set-setting state` refuses. | 069 |
| Upgrading the ledger | A migrated ledger has its `state` as the `start` entry, or none if it was unset, and the default rule list. | 064, 069 |

### 12.2 AGENTS.md

072 proposes one sentence for the Context section, after the settings
sentence: "The Bundesland history (`state_entries`) and the sampling rule list
(`sampling_rule_lists`) are ledger data with their own tables and commands,
not settings; the one recurrence vocabulary, shared with budgeting, is
`kohle/use_cases/recurrence.py`." Its purpose is to stop a later agent
(`budgeting`) from putting caps' periods into `settings` or writing a second
vocabulary. No current `AGENTS.md` statement mentions the removed flags.

---

## 13. The decision categories

### State and data lifecycle

- **`set-sampling-rules`.**
  - The whole list is parsed and validated before the transaction opens.
  - The write is a single `INSERT`, so it is atomic by construction.
  - One `Operation`, or none for an identical list.
  - Reversible: earlier lists stay in `sampling_rule_lists`, and the audit
    trail's `create` names the row. Reverting means setting the old text.
  - Replayable: `list-sampling-rules` output is the setter's input.
- **`move-state`.**
  - The state and date are validated before the transaction.
  - One `INSERT` or `UPDATE`, one `Operation`, or none when identical.
  - A correction overwrites the previous state for that D, which is not kept
    (§2.3). There is no delete (§17 item 6).
- **Nothing derived is stored.** Every history run re-derives its sample dates
  from the current list and history. So the spec's "changing it re-samples
  every past month" holds with no invalidation step, and so does "a move
  applies from D onward".
- **`init` is all-or-nothing.** The migrations, including the default-list
  seed, and `PopulateLedger` (the `start` entry and settings) all run on the
  staged file before the rename (AI §5.5).
- **`migrate` is all-or-nothing.** The `state` conversion runs inside the
  069 migration on the staged copy.
- **Downgrades refuse whenever the previous schema cannot hold what is there**
  (§8.2, §8.3).
- **Reads (`list-*`, the history) use `crud_retrieve` only and leave no
  `OperationGroup`.**
- **Snapshots and readers carry both tables unchanged.** They are ordinary
  ledger tables.

### Error propagation

- **`recurrence.py`** returns `InvalidRecurrence`, a pure value that knows
  nothing of lists or roles.
- **`sampling.py`** adds `EmptySamplingRules` and `InvalidRole`. It passes
  `InvalidRecurrence` through without re-wrapping, because that error already
  names the bad rule text and its choices.
- **`bundesland.py`** returns `InvalidState` and `NoStartState`.
- **The services** turn infrastructure failures into `SamplingError(str)` and
  `StateError(str)`, so callers above them never see SQLAlchemy.
- **The use cases** return the unions in §11.
- **`NetWorthHistory`** adds `NoStartState` and the rule errors to the
  valuation errors. It does not translate them, because their messages are
  already the user's next step.
- **The CLI** turns `Err` into `ClickException` (exit 1). Click usage errors
  (`--role`, `--from`, `--to`) exit 2 before any session opens. That keeps
  `_forbidden_factory`-style tests valid.
- **What each layer knows.**
  - `recurrence.py` knows no storage and no roles, and does not know the
    history is a table.
  - `sampling.py` knows roles, but not tables.
  - `bundesland.py` knows the `START` sentinel and the codes.
  - Only the CLI knows how things render: `start`, `-`, the role join.

### Concurrency and ownership

- **Every `kohle-cli` process is single-threaded,** with no shared mutable
  state of its own. Processes are serialised by SQLite's locking and the 30 s
  busy timeout (DT §5).
- **`_public_holidays`' cache is the one piece of process-global mutable
  state.** Bounded to 16 entries, it lives as long as the process.
  `HolidayBase` fills in years lazily on lookup, so the cache mutates its
  values on reads. That is safe single-threaded. **For `tui-wiring`:** if
  reports run in Textual worker threads, two threads may populate the same
  year at once. The `holidays` package does not promise that is safe, so guard
  the call with a lock or run reports on one worker.
- **A read-only use case's reads are not one SQLite snapshot.** Under
  pysqlite's legacy mode they run outside a transaction (DT §5.2).
  `NetWorthHistory` reads rules, states, lines and closes as separate
  statements. A `move-state` or `set-sampling-rules` that commits mid-report
  can mix that one write's before and after in that run. Every existing
  report already has this property (lines, then closes), and a re-run is
  consistent. Making reads one snapshot needs the `BEGIN` recipe that DT §5.2
  says must come with `BEGIN IMMEDIATE` for writes, which is out of scope.
- **Concurrent writers.**
  - Two `set-sampling-rules` both append, and the later id wins. Both are
    audited, and at worst two identical consecutive rows appear.
  - Two `move-state` runs for the same new D: the second fails on
    `uq_state_entry_effective_from` and is reported as a `StateError`, with
    nothing written. For one person this is a re-run, not a design problem.

### Reuse

Used, not reimplemented:

- `UnitOfWork`, `crud_create`, `crud_update` and `crud_retrieve`.
- `set_setting_service`'s create, update or no-op shape, for
  `put_state_entry_service` and, without the update, for
  `set_rule_list_service`.
- `build_ledger`'s `populate` hook and staging for `init`.
- `_KohleCommand(writes=…)` for the reader refusal.
- The `DecimalParamType` pattern for `--from`.
- `click.Choice` for `--role`, as `--state` and `--period-end` were.
- tabulate with `missingval="-"`.
- `net_worth_lines`, `aggregate_by_unit_through` and `valued_net_worth`,
  unchanged.
- Today's working-day rule, the lazy `holidays` import and the hand-written
  `STATES`, with its Augsburg comment and contract test.
- `_refuse_if_unrepresentable` in both downgrades.
- The People-root seeding precedent for the default list.

Introduced for the next piece of work:

- `recurrence.py` is what `budgeting` builds its periods on.
- `state_lookup` is what `budgeting` needs if a cap's period is `workday 25`
  (payday to payday).
- `sample_dates` is what a backfill calls to learn which closes it needs.
- `validate_state` is shared by `init.toml` and `move-state`.

### Extension points

- **Recurrence kinds.** `budgeting` adds `Every` and `Yearly`: a variant, a
  parse production, a `KINDS` entry and an `_unshifted` case. The contract:
  - `render_recurrence(parse_recurrence(t)) == t` on canonical text;
  - `occurrences` returns ascending dates in `[start, end]`;
  - a kind that does not shift never calls `state_on`;
  - stored text is the user syntax, so adding a kind needs no migration.
  Once built, the sampling list accepts them too (a fortnightly salary as
  `salary: every 2 weeks from 2026-01-02`). That is the spec's "one
  vocabulary".
- **Roles** are a closed enum (user-defined roles are a non-goal). Adding one
  is an enum member. `--role`, rendering order and parsing follow from it.
- **A backfill** calls `current_sampling_rules`, then `state_lookup`, then
  `sample_dates`. It needs no new interface.
- **No plugin extension point** is introduced. Calendars outside Germany are a
  non-goal, and `is_working_day` is the one place a calendar source would
  change.

### Build vs. buy

| Component | Decision | Evaluated, and what it could not do |
|---|---|---|
| Recurrence engine | **Build** (§3) | `dateutil.rrule` (pinned already): no holiday shift; drops dates the spec clamps; still needs our own type for rendering and the shift flag. |
| Rule parser | **Build**: `match` over `str.split()` | `pyparsing` (pinned, used by the Deutsche Bank importer): the grammar is five productions of one or two tokens, and its parse errors would have to be rewritten into the spec's "bad part plus valid choices" anyway. |
| Holiday calendar | **Buy**: `holidays` 0.106, unchanged | |
| Effective-dated lookup | **Buy**: stdlib `bisect` | |
| Storage | **Build** two small tables | The `settings` table: a key/value channel (§2.1). |

### Abstractions introduced

| Abstraction | Forcing problem |
|---|---|
| `Recurrence` sum type, five dataclasses | Round-trip rendering, the shift flag per kind, and kinds that are not monthly (`budgeting`). A callable per rule would not render. |
| `Role` enum | A fixed set, with a display order, and a `click.Choice`. |
| `SamplingRule` | A list item pairs a role with a rule. |
| `Sample` | The `role` column needs roles per date, and a backfill needs the dates without valuation. |
| `state_lookup` returning a closure | A per-date state, and the "no `start`" refusal made once. Same shape as today's `working_days` closure. |
| `InitFile` | `init.toml` is no longer a settings mapping: `state` goes elsewhere. |
| `PopulateLedger` | `init` writes two stores, and AI §7.4 wants one transaction and one group per `init`. |
| `SamplingRuleList`, `StateEntry`, two services modules | Storage (§2). |
| `EffectiveFromType` | `--from` takes `start` or a date, which no Click type accepts. |
| The errors in §11 | Each is a distinct user message. |

**Deliberately not introduced:**

- a `Protocol`/ABC or registry for kinds;
- a `StateHistory` wrapper over `Sequence[StateEntry]`;
- a `Bundesland` class (codes stay `str`);
- a generic "ledger data" table;
- a `STATE_KEY` constant;
- an `Optional` read for the rule list.

---

## 14. Alternatives rejected

- **The rule list as a reserved key in the `settings` table.** It makes
  `settings` the key/value channel (§2.1), and it breaks AI §7.4's "rows not in
  `SETTINGS` come only from a newer kohle".
- **The rule list registered in `SETTINGS`** (`set-setting sampling-rules`).
  `init.toml` would require it (every registered key is required at init), and
  the spec asks for dedicated commands and no init key.
- **One row per rule.** One replacement becomes N deletes and M creates, which
  breaks "each successful change is one `Operation`".
- **A single rule-list row updated in place.** The audit trail's `update`
  would point at a row whose old content is gone. It also needs
  `CHECK (id = 1)` and a create-or-update branch. Append-only is simpler and
  describes itself.
- **Storing the internal form (JSON, or RRULE strings).** It couples storage
  to class names or a third syntax, and every change to the internal form
  becomes a migration.
- **RRULE or `dateutil` as the internal form.** §3.2.
- **`pyparsing` for the rules.** See Build vs. buy.
- **A month-based generator (`date_in_month(rule, y, m)`).** It cannot carry
  `every N days from D`.
- **`DayOfMonth(n, shift)`, or `last day` as `day 31`.** Rendering would not
  return what the user typed.
- **`start` as a `NULL` `effective_from`.** SQLite's `UNIQUE` allows two
  NULLs, and the lookup needs a special case (§2.3).
- **Refusing a dated `move-state` until a `start` entry exists.** It makes the
  order of two commands matter to the user, and the read-time refusal already
  covers the gap.
- **The earliest entry applying backward when there is no `start`.** It
  contradicts "from D onward".
- **The default list as an app constant imported by the migration, or as a
  literal in both.** The first makes an old version script depend on evolving
  app code. The second is two places. The migration is the only writer (§8.2).
- **`PopulateLedger` writing the default list explicitly.** It would be
  redundant with the migration's seed, and an identical no-op every time.
- **Allowing an empty rule list.** §4.2.
- **`list-sampling-rules` as a role/rule table.** §5.1.
- **`list-states` marking the entry in force today.** §5.2.
- **`list-settings` showing the state in force today and the rules.** §6.
- **The `role` column second, after `date`.** Multi-word values would move the
  figure columns for whitespace-split readers.
- **An empty string, not `-`, for the `--to` row's role.** A blank cell
  collapses under `split()`, and `-` is kohle's rendering for "no value"
  everywhere else.
- **The CLI resolving rules and state and passing them to `NetWorthHistory`**
  (as 053 did for state). With no per-run override there is nothing to
  resolve, and one `UnitOfWork` reads it all.
- **`--role` filtering in the CLI after valuation.** It reads closes for rows
  it then throws away, and the TUI would duplicate it.
- **`--role` hiding a `--to` row that is a sample date of the other role.**
  §17 item 2.
- **`move-state STATE` as `click.Choice(STATES)`.** That bypasses the shared
  validator, with a different exit code and wording from `init.toml`.
- **The `set-setting state` refusal inside `validate_settings`.** The spec
  says "in the same way it refuses device keys", which is a CLI redirect.
- **`sample_dates` returning `Result` and taking the history.** The refusal
  belongs to the history (`state_lookup`), so `sample_dates` stays total.
- **One migration for both tables.** It is one migration per schema-bearing
  slice, the precedent, so each slice's downgrade is testable on its own.
- **Case-insensitive rule tokens.** One spelling per kind, as `STATES`.
- **`StateNotSet` kept with new wording.** The condition changed, from "no
  setting" to "no `start` entry", so the class is replaced.

---

## 15. Slice order and per-slice files

**The order I would change.**

1. **Fold 071 into 069. This is required.** 069 takes `state` out of
   `SETTINGS`, and `_compare_existing` compares only `SETTINGS` keys. After
   069 alone, re-running `init` with a different `state` would report "already
   initialized": the existing guarantee, tested by
   `test_existing_ledger_with_a_different_state_points_to_set_setting`, breaks
   until 071. The comparison must move in the same commit as the data. 071's
   acceptance criteria become 069's.
2. **Land 070 directly after 069, with no review or merge boundary between
   them,** or fold it in too. After 069, `NoStartState` and `init` point to
   `move-state`, which 070 adds. A migrated ledger with no state cannot be
   fixed in between. This is acceptable on the feature branch, because main
   receives the feature as one PR, but a `review` stop between them would
   review a dangling pointer.
3. **The `init.rc` → `init.toml` rename `change` (DC §13) should land before
   069.** 069 rewrites `init`'s validation, its messages and the README's
   "First run". If the rename lands later, it has to revisit all three.
4. **README: each slice deletes the statements its change makes false.** 064
   drops `--period-end` and 069 drops `--state`. 072 then writes the new
   sections. Otherwise the README describes removed flags for six slices.
   072's own scope is unchanged.

**Unchanged:**

- 064 → 065 → 066 → 067. 066 and 067 need `set-sampling-rules` for their CLI
  criteria.
- 068 anywhere after 064.
- 072 last.
- The amendments as the issues say: the portfolio amendment before 064, the
  app-initialization amendment before 069.

### 064: stored default rule list, `role` column, `day N`, `last workday`

- **Production:**
  - `recurrence.py` (new): `Day`, `LastWorkday`, `KINDS`, parse, render,
    `occurrences`, `is_working_day`.
  - `sampling.py` (rewritten): `Role`, `SamplingRule`, `Sample`, list
    parse/render, `sample_dates(rules, state_on, …)`, `current_sampling_rules`.
    `STATES` stays here for now.
  - `models.py`: `SamplingRuleList`.
  - `sampling_services.py`: `current_rule_list_service`.
  - Migration 064, and `HEAD_REVISION`.
  - `reporting.py`: `HistoryRow.roles`, and
    `NetWorthHistory.execute(start, end, max_age_days, state)`, which reads the
    rules.
  - `domain_errors.py`: the recurrence and sampling errors.
  - `cli.py`: no `--period-end`; the `role` column.
- **Tests:**
  - `conftest.py` seeds the default rule list (§18.1).
  - `test_sampling.py` is rewritten.
  - `test_recurrence.py` is new.
  - `test_net_worth_history.py`: the `PeriodEnd` test becomes a rules test.
  - `test_portfolio_cli.py`: delete the `--period-end` tests.
  - `test_migration_downgrade.py` gets `BEFORE_SAMPLING_RULES = "e5a1c3b7d902"`.
  - The equivalence golden (§18.4).
  - The guard extension (§18.6).
- **Commit message:** name the deleted `--period-end` tests as deliberate.

### 065: `set-sampling-rules`, `list-sampling-rules`, `last day`

- **Production:**
  - `LastDay`.
  - `_add_rule_list_service` and `set_rule_list_service`.
  - `SetSamplingRules` and `ListSamplingRules`.
  - Two CLI commands.
- **Tests:**
  - `test_sampling_cli.py`.
  - `test_reader.py`: add both commands to `_WRITE_ARGV` and `_read_argv`.
  - Guard: the new CLI callbacks.

### 066: `workday N`

`Workday`, its parse production and `KINDS` entry, and tests.

### 067: `<nth> <weekday>`

`NthWeekday`, the ordinal and weekday errors, and tests.

### 068: `--role`

`NetWorthHistory(role=…)` and the CLI option, with tests.

### 069 (+071): Bundesland history

- **Production:**
  - `models.py`: `StateEntry` and `START`.
  - `state_services.py`: list and put.
  - `bundesland.py`: `STATES` (moved), `validate_state`, `state_lookup` and
    `ListStates`.
  - Migration 069, and `HEAD_REVISION`.
  - `settings.py` shrinks (§9.6).
  - `ledger.py`: `InitFile`, `validate_init_file`, `PopulateLedger` and the
    `start` comparison.
  - `reporting.py`: `NetWorthHistory` reads the history and drops `state`.
  - `cli.py`: `list-states`; the `set-setting state` refusal; `init` wiring;
    `--state` removed.
  - `domain_errors.py`: the state and init-file errors; remove `StateNotSet`
    and `MissingSettings`.
- **Tests:**
  - `test_settings.py`: its state tests move to `test_bundesland.py`.
  - `test_init.py`:
    - `list-states` replaces `list-settings` for `state = BW`;
    - the audit row becomes `1 state_entries 1 create`;
    - the existing-ledger tests point to `move-state --from start`;
    - the `SetSettings.execute` monkeypatches become `PopulateLedger.execute`.
  - `test_config_commands.py`: the unknown-key message; `state` refused.
  - `test_portfolio_cli.py` and `test_price_guards.py`: `set-setting state BY`
    becomes a `start BY` seed (§18.1).
  - `test_reader.py`: `net-worth-history` loses `--state BW`; `set-setting`
    argv becomes `foo x`.
  - Migration conversion and downgrade tests.
- **Commit message:** name the `--state` and `set-setting state` tests changed
  on purpose.

### 070: `move-state`

`MoveState`, `EffectiveFromType`, the CLI command and tests. CLI test setups
switch from the direct seed to `move-state --from start BY`.

### 072: docs

§12, plus the AGENTS.md sentence.

---

## 16. Conflicts with the frozen specs being amended

The user asked for conflicts to be named, not designed around. Items marked ✓
are already listed in this spec's Dependencies section. The others are not, and
the amendments should cover them too.

### `app-initialization.md`

| Line | Current text | Conflict with this design |
|---|---|---|
| 18–19 | "a settings table in the ledger. Its first setting is the Bundesland, which `init` requires" | The Bundesland is no longer a setting. `init` requires it as the `start` entry. |
| 20–22, 65–67 | "`init` copies its values into the settings table once"; "Editing the file after `init` changes nothing; `set-setting` does." | `state` goes to `state_entries`; `move-state --from start` changes it. |
| 24–26 | "must not invent a third mechanism" | The agreed reading (ledger data, own tables) should be recorded here. |
| 59–62 | "Each key is checked with the same validator `set-setting` uses … the same set as `kohle.use_cases.sampling.STATES`" | ✓ for the validator. **Not listed:** the module path. This design moves `STATES` to `kohle.use_cases.bundesland` (§7.3). |
| 73 | step 3, "stores the settings from the file" | It stores the `start` entry, and settings when any exist. |
| 77–79 | Testable: "the settings listing shows `state = BW`" | `list-settings` no longer shows it (§6). Restate as `list-states` showing `start  BW`. |
| 84–90 | `init` on an existing database compares the stored Bundesland and "points to the setter" | ✓ |
| 115–117 | "The only key now is `state`. Sampling and budgeting add theirs later." | ✓ for `state`. After this feature there are no keys, and sampling adds none. |
| 130–135 | `net-worth-history` reads the stored Bundesland; `--state` is a per-run override; points to `set-setting state` | ✓ |
| 162–163 | Non-goal: "Changing a setting afterwards is `set-setting`'s job." | For `state`, `move-state`. |
| 180–182 | "The settings reads used by `net-worth-history` leave no `OperationGroup`" | The history now reads the rule list and the state history, which still leave no group. Reword. |
| 183–186 | "Its keys are validated against the same key list and per-key validators as `set-setting`" | No longer true (this spec's Technical Approach says so); restate. |

### `portfolio-and-profit-reporting.md`

| Line | Current text | Conflict |
|---|---|---|
| 84–94 | Sample dates are the 15th and the period end; `--period-end` | ✓ |
| 96–100 | Working day: "a public holiday of the chosen Bundesland" | The Bundesland in force on the rule's unshifted date. |
| 101–105 | `--state XX` (default `BY`) | ✓ |
| 116–117 | "The columns are: `date`, `at cost`, `at market`, `estimated`" | **Not listed:** a `role` column is added, last (§5.3). |
| 150–157 | Acceptance tests with `--period-end` and `--state` | ✓. Also restate "24 and 31 December are never sample dates under `last-working-day`" as "under `last workday`". `day 24` can sample 24 December. |
| 244–252 | Open Question on a persistent setting | ✓ |

### `device-config.md` (not named in this spec's Dependencies)

| Line | Current text | Conflict |
|---|---|---|
| 6–7 | "**Ledger settings** are facts about the books, such as the Bundesland. They live in the `settings` table" | The Bundesland is ledger data in `state_entries`, not a setting. The amendment is only to the example; nothing in device-config's mechanics changes. Whether to amend is the user's call. |

---

## 17. Gaps in the spec, and points for the user

1. **"Empty role" renders `-`** (§5.3), following the `missingval="-"`
   convention. A literal blank is a one-value change (`""` in place of `None`)
   if preferred.
2. **`--role` always keeps the row dated `--to`,** even when `--to` is a
   sample date of the other role. Issue 068 says "when it is not a sample
   date". The spec says "The `--to` row is always shown". The design takes
   the reading where the "now" row never disappears on the 15th.
3. **`init` stores the default rule list by running the 064 migration,** as it
   gets the People root. Its populate step writes only the `start` entry and
   settings. The rule list in a fresh ledger has no `Operation`; the `start`
   entry does.
4. **An empty rule list is refused** (§4.2). Issue 065 left this to design.
5. **"No Bundesland entry" (spec) vs. "no `start` entry" (issue 069).** The
   design refuses whenever there is no `start` entry, which includes "no
   entry". A dated `move-state` before any `start` entry is accepted, and the
   history refuses until `start` exists (§9.4).
6. **No way to remove a state entry.** A mistaken dated entry can only be
   neutralised by re-recording that D with the state in force before it. It
   stays in `list-states`. Removal belongs to `undo-delete-edit`.
7. **A row dated before a move can use the new state's holidays.** This
   happens when its unshifted date is on or after the move date. Example:
   after `move-state --from 2026-01-01 NI`, `workday 1` for January has
   unshifted date 1 January, which is NI, and lands on 30 December 2025, using
   NI's calendar. The spec's "changes no row dated before 2026-01-01" holds
   exactly for the default list. For `workday 1`-style rules it holds only
   where the two calendars agree on the days crossed. This is the spec's
   explicit rule, and the design follows it.
8. **`every …` and `yearly …` are rejected until `budgeting` builds them,**
   with "invalid rule … expected one of" listing the built kinds. The README
   (072) documents them as specified but not built.
9. **For `budgeting`'s spec:**
   - `every N months from D` with D on the 29th–31st, and `yearly 02-29`, are
     undefined for short months. RFC 5545 would skip; `day N` clamps.
     Recommend clamping, for one meaning across the vocabulary.
   - Also undefined: whether `every` and `yearly` can shift. The spec's table
     implies not.
10. **`set-setting` accepts no key after this feature,** and `list-settings`
    shows only the path and revision. Both stay because the spec keeps
    `set-setting` (it must refuse `state`) and `budgeting` may add keys.
11. **`last workday` and `workday 31` mean the same,** as do `last day` and
    `day 31`. Both spellings are accepted and listed as typed.
12. **The rule-list history grows by one row per real change** and is never
    pruned. That is negligible at personal scale.

---

## 18. Testing notes

### 18.1 Fixtures

- **`conftest.py`'s `session` and `session_factory` seed the default rule
  list** right after `create_all`, with a direct insert of
  `SamplingRuleList(rules="mid-month: day 15; salary: last workday")` and no
  `Operation`. This mirrors the migration's unconditional seed, which every
  ledger at head has.
  - Seeding is automatic, unlike opt-in `people_root`, because no ledger at
    head lacks a rule list, and `current_rule_list_service` relies on that
    (`.one()`).
  - `test_price_guards.py`'s `_fresh_factory` builds its own schema and needs
    the same seed. Factor one helper.
- **No automatic state seed.** A ledger with no `start` entry is legitimate (a
  migrated unset ledger), and its refusal must be testable.
  - Add an opt-in `start_state` fixture for `session` tests, inserting
    `StateEntry(effective_from=START, state="BY")`.
  - In 069, CLI setups seed it the same way through `session_factory`.
  - From 070 on, they run `move-state --from start BY`.

### 18.2 `recurrence.py` (layer 1, pure)

- **Round trips:** parse then render is the identity for each kind and for
  `day 5` vs `day 05`. Whitespace is normalised.
- **Errors:** one per row of §11's `expected` table, plus `day 0`, `day 32`,
  `day x`, `Day 15` (case), `every 2 weeks from 2026-01-02` and
  `yearly 12-24`.
- **Unshifted dates and clamping:**
  - `day 31` and `last day` in February 2026 give the 28th, and in 2028 the
    29th.
  - `day 30` in April gives the 30th.
- **Shifts (BY, holidays 0.106, verified):**

  | Rule | Month | Lands | Why |
  |---|---|---|---|
  | `day 15` | 2026-02 | Sun 2026-02-15 | never moves |
  | `workday 15` | 2026-02 | Fri 2026-02-13 | 15th is a Sunday (also 2026-03) |
  | `last workday` / `workday 31` | 2026-02 | Fri 2026-02-27 | |
  | `1st fri` | 2026-05 | Thu 2026-04-30 | 1 May holiday; lands in the previous month |
  | `1st fri` | 2026-04 | Thu 2026-04-02 | Karfreitag 3 April |
  | `3rd fri` | 2026-05 | Fri 2026-05-15 | a working day; the "one row, both roles" month |
  | `last workday` | 2028-12 | Fri 2028-12-29 | 30th Saturday, 31st excluded |

- **Range edges:**
  - `occurrences(1st fri, 2026-04-01, 2026-04-30, BY)` is `[04-02, 04-30]`.
    That proves next month's date is considered.
  - An occurrence after `end` is excluded.
- **Lazy import:** a subprocess with `-I`, like the existing lazy-import
  checks, shows that `sample_dates` with only `day`/`last day` rules leaves
  `holidays` out of `sys.modules`.
- **Moved here from `test_sampling.py`:** the working-day parametrised table.

### 18.3 `sampling.py` and `bundesland.py` (layer 1)

- **List parsing:**
  - `""` and `";"` give `EmptySamplingRules`.
  - `day 15` gives `InvalidRole(role=None)`.
  - `pay: day 15` gives `InvalidRole("pay")`.
  - A bad rule passes `InvalidRecurrence` through.
  - A trailing `;` is accepted.
  - A repeated role is kept.
- **Merging:**
  - `mid-month: day 15; salary: 3rd fri` over May 2026 gives one
    `Sample(2026-05-15, (mid_month, salary))`.
  - Two salary rules on one date give `(salary,)`.
  - Roles are always in enum order, whatever the list order.
- **The `--to` row:** appended with `()` unless `end` is already a sample
  date, in which case it keeps its roles.
- **Move to NI** (`[START BY, 2026-01-01 NI]`, default list):
  - the October 2025 salary sample is Friday 2025-10-31;
  - the October 2028 salary sample is Monday 2028-10-30;
  - every sample before 2026-01-01 equals the BY-only result.
  All three verified by prototype.
- **`state_lookup`:**
  - Covers `start` only, the move date itself, and a future D.
  - An empty history and a dated-only history both give `NoStartState`.
- **`validate_state`:** all 16 codes pass. `XX`, `by`, `""`, `1`, `None` and
  `["BY"]` fail with `expected one of …`, moved from `test_settings.py`.
  `Augsburg` is rejected. The `holidays` contract test moves with `STATES`.

### 18.4 The pre-feature equivalence (spec testable, 064)

- **Pure level.** `sample_dates(default, lambda _: "BY", a, b)` dates must
  equal the pre-feature `sample_dates(a, b, last_working_day, "BY")` over many
  ranges. A prototype of this design matched on 300 random ranges, 2000–2043.
  - Before deleting the old function, the implementer captures its output
    over one long range (2000-01-01 to 2040-12-31) into
    `tests/fixtures/sample_dates_last_working_day_by.txt`.
  - The new test compares against that file. The old code is the oracle, and
    no reimplementation of it lives in the tests.
- **Figures.** At the start of 064, before changing code, capture the
  pre-feature output of `net-worth-history --period-end last-working-day
  --state BY` for `test_portfolio_cli`'s `_SETUP` ledger. Use a multi-year
  `--from`/`--to` with `_pin_today`, so it covers Karfreitag 2024, Saturday
  2026-10-31 and December 2028.
  - Store it as `tests/fixtures/net_worth_history_pre_sampling.txt`.
  - After the change, each data line's `split()[:6]` (date, at cost, at
    market, `K of M`) must equal the fixture's. The role is the last column,
    so nothing else moves.
- **"After migrate".** 064 tests that a ledger migrated from `e5a1c3b7d902`
  holds exactly the default list. 069 tests that a ledger with `state = BY`
  migrates to `[START BY]`, with no `state` row left in `settings`.
  - Those are exactly the inputs of the figures test, so together they prove
    the spec's sentence without a pre-feature CLI running against a file at a
    pre-feature revision.
  - Read the stored list back through the model and assert that it parses and
    renders to itself.

### 18.5 Migrations (`test_migration_downgrade.py`)

- **064:**
  - The upgrade seeds the default.
  - A round trip works with only the default.
  - The downgrade refuses after a real `set-sampling-rules`, whether that
    leaves two rows or one non-default row.
  - A refusal leaves the table in place.
- **069:**
  - A `state = BY` setting converts to `('0001-01-01', 'BY')`, and that row
    reads back as `START` through `StateEntry`.
  - An unset state creates no entry.
  - The `settings` row is gone.
  - A round trip with `start` only restores `state = BY`.
  - The downgrade refuses with a dated entry.
- `HEAD_REVISION` is pinned after each.

### 18.6 Guards and counts (`test_price_guards.py`)

- **AST guard:** add `recurrence.py`, `sampling.py`, `bundesland.py`,
  `sampling_services.py`, `state_services.py` and the callbacks of the four
  new commands to the sources that must not reference `FORBIDDEN_IDENTIFIERS`
  or `PRICE_MODULES`.
- **Transitive import check:** add `kohle.use_cases.recurrence`,
  `kohle.use_cases.sampling` and `kohle.use_cases.bundesland` to it.
- **Behavioural:** run each new or changed command
  (`set-sampling-rules`, `list-sampling-rules`, `move-state`, `list-states`,
  `net-worth-history --role salary`) with the plugin loader patched to fail.
  The `prices` row count must stay the same.

### 18.7 CLI (layer 3)

- **`list-sampling-rules`** prints exactly the canonical line.
- **`set-sampling-rules`:**
  - An invalid list exits 1, names the bad part and the choices, and leaves
    the `list-sampling-rules` output and the `operations` count unchanged.
  - An identical set adds no group.
  - A real set adds `create sampling_rule_lists <id>`.
- **One sample row per month.** `set-sampling-rules "salary: workday 25"` and
  `"salary: last day"` give exactly one sample row per month, plus the `--to`
  row.
  - Choose `--to` on or after the last month's occurrence. A partial final
    month whose occurrence falls after `--to` has none. Checked: October
    2026's `workday 25` is the 23rd.
  - The property holds only for kinds whose shift cannot cross a month
    boundary. With `1st fri` or `workday 1`, one month can have two rows and
    the next none, so do not generalise the test.
- **`move-state`:**
  - `--from bogus` exits 2.
  - `XX` exits 1 with the code list and writes nothing.
  - Repeating a D gives one `update`.
  - The same D and state add no group.
  - A future D is accepted.
- **`list-states`:** the empty message, `start` rendering, and oldest first.
- **`net-worth-history`:**
  - With no `start` entry it exits 1 with `move-state --from start <code>`.
  - `--role salary` keeps the `--to` row.
  - `--role bogus` exits 2 without a session.
  - The role column appears with `mid-month, salary` and `-`.
- **`set-setting state BY`** exits 1, points to `move-state`, and writes
  nothing.
- **`init`:**
  - `list-states` shows `start  BW`.
  - Re-running with a different `state` exits 1, points to
    `move-state --from start`, and leaves the file byte-identical.
  - Re-running after the `start` entry is deleted by SQL does the same.
