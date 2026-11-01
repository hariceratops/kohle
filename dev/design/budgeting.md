# Design: Budgeting

Spec: `dev/specs/budgeting.md` (frozen). Issues: `dev/issues/074`–`081`.

Abbreviations: **CS** is `dev/design/configurable-net-worth-sampling.md`,
**AI** is `dev/design/app-initialization.md`, **DT** is
`dev/design/device-topology-and-sync.md`.

**Upstream state this design assumes.**

- The spec is in `dev/specs/`, so this design treats it as frozen. The move
  out of `dev/inbox/` is not committed yet: git shows the inbox copy deleted
  and the spec untracked.
- The spec's two open questions take their defaults: the new kinds are valid
  in `set-sampling-rules`, and a cap of 0 is valid.
- §15 lists the gaps and readings. The user has settled all of them. Item 1
  changes the spec's cut-at-D rule: an entry identical to the one in force
  before it does not cut (§4.1). This is a deliberate, user-approved
  refinement. The spec's wording should be revised to match; the user is
  doing that, and no agent edits `dev/specs/`. Items 2–13 are accepted as
  proposed.

---

## 1. Summary of the shape

| Concern | Decision | § |
|---|---|---|
| Internal recurrence form | Keep the closed sum type. Add `Every` and `Yearly`. One ascending generator per kind sits under `occurrences` and the new `next_occurrence`. No RRULE and no `dateutil`. | 2 |
| `N` in `every N …` | 1 to 999, so every boundary stays a representable date | 2.3 |
| Cap history storage | Its own table, `cap_entries`, with one row per account and effective date. `amount` and `rule` both NULL mark an end entry. The rule is stored as canonical user syntax. Repeating a D updates the row in place. | 3 |
| Periods | A pure `cap_periods(history, state_on, through)`. Each entry's periods run from its D, and the next entry cuts them, unless it repeats the entry before it (user decision, refining the spec). | 4 |
| Which accounts take part | One partition, `budget_accounts`. Cappable means expense type, outside `People`, and outside `Unclassified Expense`'s subtree. `set-cap` accepts exactly that set, and the uncapped row counts only lines on it. | 5 |
| Bundesland | `budget` refuses with `NoStartState` only when a cap entry uses a shifting kind. `set-cap` never checks. | 4.5 |
| `budget` range | `--to` after today is a usage error, as in `net-worth-history` | 6.3 |
| `list-caps` | One table: account, from, cap, rule. Accounts by name, entries oldest first. An end entry shows `-` and `no cap`. | 6.1 |
| `budget` | One table: account, from, to, cap, spent, over/under, note. Period rows come by account, then by start. The `Unclassified Expense` and `(uncapped)` rows always follow. | 6.2 |
| Modules | `kohle/use_cases/budgeting.py` and `kohle/services/cap_services.py`. Not `reporting.py`, which holds the reports that read prices. | 7 |
| Slice order | Unchanged. 076 builds the whole tiling, 077 narrows the Bundesland refusal, 078 adds `short`, and 075 ships replace-by-D. | 14 |

New files:

| File | Contents | Slice |
|---|---|---|
| `kohle/use_cases/budgeting.py` | Account partition, cap values, the pure period and attribution functions, `SetCap`, `EndCap`, `ListCaps`, `QueryBudget` | 075–080 |
| `kohle/services/cap_services.py` | Cap-entry list, create, update, put | 075 |
| `kohle/db/migrations/versions/<rev>_cap_entries.py` | Table and downgrade | 075 |
| `tests/test_budgeting.py`, `tests/test_budgeting_cli.py` | See §16 | 075–080 |
| `tests/fixtures/occurrences_monthly_kinds.txt` | Oracle captured before the 074 rewrite (§16.1) | 074 |

Changed: `kohle/use_cases/recurrence.py`, `kohle/domain/models.py`,
`kohle/domain/domain_errors.py`, `kohle/db/schema.py` (`HEAD_REVISION`),
`kohle/app/cli/cli.py`, `README.md`, `AGENTS.md`, and the tests named per
slice in §14. `kohle/use_cases/sampling.py` and `reporting.py` do not change.

**The existing patterns this follows.** The Bundesland history is a table of
its own (`state_entries`). It has a services module that creates, updates or
skips a write (`put_state_entry_service`), and a use-case module that holds
the pure functions beside the `UnitOfWork`s (`bundesland.py`, `sampling.py`).
Its CLI listing is a tabulate table with `from` first (`list-states`). The cap
history copies each of these. The account partition copies
`balance_sheet_accounts`. Lines are read through `account_lines_service`, as
`net_worth_lines` does.

---

## 2. Decision 1: the internal recurrence form and the two new kinds

### 2.1 The sum type stays

CS §3.2 rejected RRULE (`dateutil.rrule`, already pinned) for four reasons,
and they still hold. The two new kinds add three more:

1. **"In both directions from A".** RRULE generates forward from `DTSTART`.
   Occurrences before A need a `DTSTART` that we compute backward ourselves,
   and that is the same arithmetic the kind needs on its own.
2. **Clamp without drift.** `FREQ=MONTHLY;BYMONTHDAY=31` skips short months,
   but `every 1 months from 2026-01-31` must land on 02-28 and then 03-31.
   `FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29` skips three years in four, but the
   spec wants 28 February.
3. **A period ends at "the first occurrence after a date",** and how far
   ahead that is has no fixed bound (`every 999 months` is 83 years).
   `rrule.after()` exists, but only on an RRULE we would still have to build
   with the clamp workarounds.

`dateutil.relativedelta` was evaluated for the month step on its own.
`anchor + relativedelta(months=k*n)` clamps without drifting, which is
correct. It is not used. The month-index arithmetic is the same length, it
also yields the first index on or after `start` directly, and it keeps
`recurrence.py` on the standard library plus the lazily imported `holidays`.

### 2.2 The kinds

```python
@dataclass(frozen=True, slots=True)
class Every:          # every N days|weeks|months from YYYY-MM-DD
    n: int            # 1-999
    unit: Literal["days", "weeks", "months"]
    anchor: date      # fixes the phase only

@dataclass(frozen=True, slots=True)
class Yearly:         # yearly MM-DD
    month: int
    day: int          # 1 to that month's length in a leap year

Monthly = Day | Workday | NthWeekday | LastWorkday | LastDay
Recurrence = Monthly | Every | Yearly

KINDS = ("day N", "workday N", "<nth> <weekday>", "last workday", "last day",
         "every N days|weeks|months from YYYY-MM-DD", "yearly MM-DD")
```

- This is CS §3.1's planned `Every(n, unit, anchor)`, unchanged.
- `unit` is a `Literal` of the user's words, so rendering needs no table.
- **`Monthly` is forced by `_unshifted(rule, year, month)`.** That function
  only has meaning for the five month-based kinds. With the alias, its
  `assert_never` stays exhaustive and does not need cases that cannot occur.
- **Rendering:** `every {n} {unit} from {anchor.isoformat()}` and
  `yearly {month:02d}-{day:02d}`. Parsing and then rendering is the identity
  on canonical text, which is CS §4.3's contract.

### 2.3 Grammar and errors

```
rule := … | "every" N UNIT "from" DATE | "yearly" MD
N    := 1..999 in decimal digits
UNIT := "days" | "weeks" | "months"
DATE := YYYY-MM-DD, parsed with datetime.strptime(text, "%Y-%m-%d")
MD   := M "-" D, one or two digits each, naming a day that exists in a leap year
```

- **Plural units only,** as the spec writes them (`every 1 months`). This is
  CS §4.1's "one spelling per kind". `every 1 month` is refused, and the
  error names the three units.
- **`years` is refused.** The error says to write months, which is the
  spec's rule for multi-year periods.
- **N runs from 1 to 999.** `_ascending` builds the next date before its
  consumer compares it with `end`, and `next_occurrence` has to build the
  first date after a period. For an absurd N that date lies past 9999-12-31,
  and `date` raises `OverflowError`. That would reach the user through
  `DbTransaction.execute`'s broad catch as "signed integer is greater than
  maximum". With 999 months (83 years) at most, every boundary reachable from
  today's dates is representable, and the bound becomes a parse error that
  states the range. The prototype hit the overflow at N = 10¹².
- **`yearly` accepts one or two digits per field** and renders `MM-DD`, as
  `day 05` renders `day 5`. `02-29` is valid. `02-30`, `04-31`, `00-10` and
  `13-01` are refused.
- **`DATE` uses the CLI's strict date format, not `date.fromisoformat`,**
  which also accepts `20260101` and week dates (CS §10.2). `strptime`
  accepts `2026-1-5`, and the render gives `2026-01-05`.
- **The `every` and `yearly` cases come first** in `parse_recurrence`'s
  `match`. Otherwise `yearly 13-01` falls through to the two-token
  ordinal/weekday cases and gets the generic "one of" error.

`InvalidRecurrence.expected`, naming the bad part and the choices:

| Bad part | `expected` |
|---|---|
| `every` with the wrong token count, or no `from` | `every N days, weeks or months from YYYY-MM-DD` |
| N not digits, 0 or over 999 | `every N … with N from 1 to 999` |
| Unit (`years`, `month`, …) | `a unit days, weeks or months; for years write months, e.g. every 24 months` |
| Anchor | `a date YYYY-MM-DD after from` |
| `yearly` with anything but one valid `MM-DD` | `yearly MM-DD naming a calendar day, e.g. yearly 02-29` |
| Unknown kind | `one of: ` plus all seven `KINDS` |

### 2.4 Generation: one ascending generator per kind

```python
def _ascending(rule: Recurrence, start: date, state_on: Callable[[date], str]) -> Iterator[date]:
    """Every date the rule lands on from `start` onward, ascending, without end."""

def occurrences(rule, start, end, state_on) -> list[date]:            # signature unchanged (074)
    return list(takewhile(lambda day: day <= end, _ascending(rule, start, state_on)))

def next_occurrence(rule, after, state_on) -> date:                   # 076
    """The first date the rule lands on strictly after `after`."""
    return next(_ascending(rule, after + timedelta(days=1), state_on))

def shifts(rule: Recurrence) -> bool                                  # today's _shifts, public from 077
```

What `_ascending` does per kind:

- **`Every` in days or weeks.** The step is `n` or `7n` days. With `a` as
  the anchor's ordinal, the first ordinal on or after `start` is
  `a + k·step`, where `k = -((a - start.toordinal()) // step)`, the ceiling
  of `(start - a) / step`. The generator steps from there. A date is built
  only for an ordinal it actually yields.
- **`Every` in months.** The month index is `12·year + month − 1`. Start at
  `k = (index(start) − index(anchor)) // n`. Occurrence k is the anchor's day
  clamped to the month at `index(anchor) + k·n`. It is yielded when it is on
  or after `start`. Each occurrence is computed from A itself, so it never
  drifts: 01-31, 02-28, 03-31.
- **`Yearly`.** For each year from `start.year`, the day is clamped to the
  month, and the date is yielded when it is on or after `start`.
- **The five month-based kinds.** Today's walk, starting at `start`'s month
  with no end bound. Take the unshifted date. If the kind shifts, move it back
  to a working day under `state_on(unshifted)`. Yield it when it is on or
  after `start`.

Why a generator:

- **`next_occurrence` needs "the first date after D" for kinds whose gap has
  no fixed bound.** A range API would need a guessed window.
- **It replaces CS §3.3's "walk through the month after `end`".** The walk
  goes on until a date passes `end`, so a date from the following month that
  shifts back into the range is still found. One example: with
  `--to 2026-04-30`, May's `1st fri` shifts back to 04-30.
- **The `sorted(found)` goes, because the month-based kinds are strictly
  ascending after shifting.** Consecutive unshifted dates are at least 28
  days apart, and a shift is at most 5 days (CS §3.3, measured).
- **Verified by prototype.** The 36 month-based rules tested were day
  1/15/31, workday 1/25/31, last day, last workday, and all 28 nth-weekday
  rules. Under a BY→NI move on 2026-01-01, all 36 were strictly ascending
  from 2000 to 2045. They also equalled today's `occurrences` on 28,800
  (rule, random range, history) cases.

**`Every` and `Yearly` never shift** and never call `state_on`. That is CS's
extension contract ("a kind that does not shift never calls `state_on`"), so
a rule list made only of these kinds never imports `holidays`.

### 2.5 `set-sampling-rules` accepts the new kinds with no change to `sampling.py`

`parse_sampling_rules` already calls `parse_recurrence`, and `sample_dates`
calls `occurrences`. Stored lists are user syntax, so no migration is needed
(CS §2.2). A list such as `salary: every 2 weeks from 2026-01-02` samples
every other Friday.

Two fixtures show that existing lists give the same `net-worth-history`:
the 064 golden fixture of sample dates, and a fixture for the month-based
kinds captured before the rewrite (§16.1).

---

## 3. Decision 2: storage of the cap history

### 3.1 `cap_entries`

```python
class CapEntry(base):
    """A spending cap on an expense account from `effective_from` onward, until
    the account's next entry. `amount` and `rule` both NULL: no cap from that
    date (end-cap)."""

    __tablename__ = "cap_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(QUANTITY, nullable=True)
    rule: Mapped[str | None] = mapped_column(String, nullable=True)   # canonical user syntax

    account: Mapped["Account"] = relationship("Account")

    __table_args__ = (
        UniqueConstraint("account_id", "effective_from", name="uq_cap_entry_account_effective_from"),
        # Readers branch on `amount is None` and parse `rule` otherwise, so half
        # an end entry must not be storable.
        CheckConstraint("(amount IS NULL) = (rule IS NULL)", name="ck_cap_entry_end_is_both_null"),
    )
```

- **A table of its own, not the `settings` table.** CS §2.1's reasons carry
  over. A key/value row cannot hold a date and an account per row without
  encoding them into the key, and the spec forbids "a general key/value
  channel". With no key column, nothing else can be stored there without a
  migration. `list-operations` names it `cap_entries`.
- **`UNIQUE(account_id, effective_from)`** is the spec's "one entry in force
  at a time" and "repeating an existing D … replaces the entry". It also
  gives the index that per-account reads use.
- **An end entry is a row whose `amount` and `rule` are both NULL.** The
  codebase already uses NULL to mean something
  (`Classification.matched_rule_id`, `Split.adjusting_entry_id`). One table
  means a cap and an end at the same D are mutually exclusive under one
  `UNIQUE`. The `CHECK` keeps the two columns paired. That is the one
  invariant the readers rely on, so it lives in the schema.
- **`rule` holds the canonical user syntax** (CS §2.2). New kinds need no
  migration, the row reads in `sqlite3`, and it is exactly what `list-caps`
  prints. The column is named `rule` because the vocabulary calls these
  rules (`invalid rule …`, the README's "Sampling rules").
- **`amount` is `QUANTITY`,** the column type every journal amount uses. It
  has no unit column, because caps are in the base currency only.
- **Replacing an existing D updates the row in place** with `crud_update`,
  which records one `Operation`. An identical entry writes nothing. This is
  `state_entries` exactly (CS §2.3). The previous values of a corrected entry
  are not kept, as for every other update; that belongs to
  `undo-delete-edit`.
- **There is no delete.** The spec gives no removal. A mistaken D can only
  be corrected by recording the entry in force before it at that D. The
  identical-entry rule (§4.1) keeps that correction from cutting the period
  and doubling the cap (§15 item 1).
- **There is no `start` sentinel.** `--from` takes a date only. A cap in
  force "from the start of the ledger" would make its first period start in
  year 1.
- **No `Archivable` and no `created_at`.** The `OperationGroup` records
  when, and rows are never deleted.
- **The foreign key to `accounts` is safe** because accounts are only ever
  soft-deleted.

### 3.2 Migration `<rev>_cap_entries.py` (075, revises `a7c3e9d5b124`)

- **Upgrade:** `create_table('cap_entries', …)` with the foreign key, the
  `UNIQUE` and the `CHECK` above. No seed: a ledger without caps is the
  normal state.
- **Downgrade:** `_refuse_if_unrepresentable` refuses when the table has any
  row, because the previous schema has no caps. This is the rules-table
  precedent. Otherwise it runs `drop_table`.
- **The NULLable columns ship in 075** even though nothing writes an end
  entry until 079. Making them nullable later would need a batch-mode table
  rebuild in SQLite, which costs a second migration for nothing.
- **`HEAD_REVISION`** in `kohle/db/schema.py` takes the new revision.
  `test_schema_check` pins it.

---

## 4. Periods

### 4.1 Definition

An account's history is its entries, oldest first.

- **An entry identical to the one before it does not cut.** Before tiling,
  an entry is dropped when its cap equals the cap of the entry immediately
  before it in the history: the same amount and the same rule, or both end
  entries. The earlier entry's span then runs on through it.
  - **This refines the spec, with the user's approval.** The spec says "An
    entry taking effect at D ends the running period on D−1 and starts a new
    period at D", with no exception. The spec text should be revised to say
    "unless it repeats the entry in force before it".
  - **Why.** There is no delete, and a cap is never prorated. Under the
    literal rule, the only repair of a mistaken D (recording the previous
    cap again at that D) splits the running period into two short halves,
    and each half gets the full cap. Example: 300 `day 1` from 01-01, then a
    mistaken 400 from 03-10 that should have been 04-01. The repair is to
    re-set 300 at 03-10 and add 400 at 04-01. March is then one full period
    at 300, not 03-01–03-09 and 03-10–03-31 at 300 each, which would be 600
    for the month.
  - **Only the immediately preceding entry counts.** A, then B, then A cuts
    at both changes.
  - **The entry is still recorded.** `set-cap` writes it as one `Operation`
    and `list-caps` shows it, because the history is shown as recorded.
    Only the period tiling ignores it. Attribution is unaffected, because
    the same cap is in force either way.
- **The span of entry i** is `[Dᵢ, Dᵢ₊₁ − 1]`. The last entry's span is
  open-ended. An end entry's span has no periods.
- **The periods of a cap entry with rule r.** The first starts at `Dᵢ`. A
  period starting at `s` ends at `e = min(next_occurrence(r, s) − 1, span
  end)`. The next starts at `e + 1`.
- **Short.** A period is short when its start is not an occurrence of r, or
  when its end was cut by the span (`e ≠ next_occurrence(r, s) − 1`). The
  first can only happen to an entry's first period, where `s = Dᵢ`. The cap
  is never prorated.
- **Natural boundaries are not cuts.** When `Dᵢ₊₁` is itself an occurrence
  of r, the period ending on `Dᵢ₊₁ − 1` ended naturally and is not short.
  This applies to an end entry too. §15 item 9 covers 079's wording.

The spec's examples, all reproduced by the prototype, then the
identical-entry rule:

| History | Periods |
|---|---|
| 300 `day 1` from 01-01; 400 `day 1` from 03-10 | Jan, Feb full at 300; 03-01–03-09 short 300; 03-10–03-31 short 400; Apr full 400 |
| `every 1 months from 2026-01-31` from 01-31 | 01-31–02-27, 02-28–03-30, 03-31–04-29 |
| `every 3 months from 2026-01-15` from 01-01 | 01-01–01-14 short; 01-15–04-14 |
| `yearly 02-29` | a boundary on 2027-02-28 |
| 300 `day 1` from 01-01; end from 04-01 | Jan–Mar full; nothing from April |
| 300 `day 1` from 01-01; end from 04-10 | Jan–Mar full; 04-01–04-09 short |
| `workday 25` from 2025-09-25, BY | 09-25–10-23, 10-24–11-24, 11-25–12-22 (24 and 25 December are not working days), 12-23–2026-01-22, … |
| 300 `day 1` from 01-01; 300 `day 1` from 03-10 | Jan, Feb, Mar, Apr full at 300; the second entry cuts nothing |

### 4.2 The pure builder

```python
@dataclass(frozen=True, slots=True)
class Cap:
    amount: Decimal
    recurrence: Recurrence

@dataclass(frozen=True, slots=True)
class CapChange:
    """One entry of an account's cap history, with its rule parsed. `cap` None
    is an end entry: no cap from `effective_from`."""
    effective_from: date
    cap: Cap | None                     # `Cap` only, until 079

@dataclass(frozen=True, slots=True)
class Period:
    start: date
    end: date
    cap: Decimal
    short: bool                         # 078

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

def cap_periods(
    history: Sequence[CapChange], state_on: Callable[[date], str], through: date
) -> list[Period]:
    """One account's periods that start on or before `through`, oldest first
    (§4.1). Total: no Result, no session, no prices."""
```

- **Identical consecutive entries collapse first.** `cap_periods` drops each
  `CapChange` whose `cap` equals the previous one's, then tiles the rest.
  - `Cap` equality is field equality. `Decimal('300') ==
    Decimal('300.00000000')`, and both rules are parsed from canonical text,
    so stored and typed values compare correctly.
  - This is the only place the rule lives. `in_force`, `list-caps`,
    `put_cap_entry_service` and `EndCap` are unchanged.
- **Periods are generated from each entry's D, not from `--from`.** A period
  after an entry's first one starts on an occurrence. Jumping to the period
  that contains `--from` would need a `previous_occurrence` primitive, and an
  entry's first period differs from the rest anyway. A daily cap over years
  gives a few thousand periods, which costs nothing at personal scale.
- **Whether `Dᵢ` is an occurrence** is `occurrences(r, Dᵢ, Dᵢ, state_on) ==
  [Dᵢ]`. It uses the existing range API, so no third primitive is needed.

### 4.3 Which periods are shown

`period_rows` (§5.4) calls `cap_periods(…, through=min(--to, today))` and
keeps a period when `period.end >= --from`.

- **"Periods that start after today are not shown"** is held by the
  generation bound in the use case, not by the CLI. A TUI caller gets the
  same rule. The CLI also refuses `--to` after today (§6.3), so the bound is
  `--to` in practice.
- **Shown whole:** start, end and spending are never clipped to the range.

### 4.4 Partial

A period that contains today (`start ≤ today ≤ end`) carries `day =
(today − start).days + 1`. The note shows `partial day {day} of
{period.days}`, so today counts. The use case computes `day`, so a TUI does
not repeat the date arithmetic.

### 4.5 The Bundesland: refused only when a shifting kind needs it

The spec says "The shifting kinds … Without a Bundesland entry they refuse",
and issue 077 says the same. So `budget` without a `start` entry still works
for `day`, `last day`, `every` and `yearly` caps. In `QueryBudget`:

```python
lookup = state_lookup(state_entries)
if lookup.is_err and any(c.cap is not None and shifts(c.cap.recurrence) for h in histories for c in h):
    return Result.err(lookup.unwrap_err())          # NoStartState, pointing to move-state --from start
# Only a shifting kind calls state_on, and with no start entry the line above ruled those out.
state_on = lambda day: lookup.unwrap()(day)
```

- **It checks every cap entry, not only the ones in range.** The rule is then
  deterministic, and the fix is one `move-state --from start`.
- **`set-cap` does not check.** Refusing there would make the order of two
  commands matter to the user. CS §14 rejected the same for a dated
  `move-state` before `start`.
- **Slices.** 076 refuses whenever there is no `start` entry, as
  `net-worth-history` does. 077 narrows that to the condition above (§14).

---

## 5. Spending and attribution

### 5.1 One account partition

```python
@dataclass(frozen=True, slots=True)
class BudgetAccounts:
    accounts: dict[str, Account]        # every account, by name
    people: frozenset[int]              # the People subtree
    unclassified: frozenset[int]        # Unclassified Expense's subtree; empty before the first import

    def cappable(self) -> list[Account]:
        """Expense accounts outside both subtrees, by name: what set-cap
        accepts, and the accounts whose lines the uncapped row counts."""

def budget_accounts(ctx: DbTransactionContext) -> Result[BudgetAccounts, AccountError]
def check_cappable(accounts: BudgetAccounts, name: str) -> Result[Account, UncappableAccount]
```

- **One definition for three use cases.** `SetCap`, `EndCap` and
  `QueryBudget` all need it. This is the precedent of `balance_sheet_accounts`
  ("Shared so 'own account' has one definition").
- **`budget_accounts` reads:**
  - `list_accounts_service`;
  - `descendant_account_ids_service` under `PEOPLE_ROOT`, which every ledger
    at head has from the people-root migration;
  - `descendant_account_ids_service` under `UNCLASSIFIED_EXPENSE`, when that
    account exists. `AccountNotFoundError` there means an empty set. It is a
    real state before the first import, so this is not defensive code.
- **`check_cappable` checks in this order,** so each message names the real
  problem: missing, then in `Unclassified Expense`'s subtree, then under
  `People`, then not of expense type. Person accounts are usually of type
  `expense` (the `add-account` default), and `Unclassified Expense` always
  is, so a type check alone would let both through.
- **A parent is cappable** when it passes the same checks. Parents and leaves
  are treated alike.

### 5.2 What a cap covers

`CappedAccount.covers` is the capped account's
`descendant_account_ids_service` set minus `BudgetAccounts.unclassified`.

- **The subtree is the spec's** "the capped account and its subtree". It is
  the SQL CTE `balance` uses, cycle-safe, and is not reimplemented in Python.
- **Lines in the `Unclassified Expense` subtree count toward no cap.** The
  spec says "A line in `Unclassified Expense` appears only in the
  unclassified row". That can only matter if the user created
  `Unclassified Expense` under a parent before the first import and then
  capped the parent (§15 item 3).
- **Every type in the subtree counts.** An asset child under a capped expense
  parent counts toward the cap. That is the literal "subtree" (§15 item 5).

### 5.3 Spending

```python
def net_spent(lines: Iterable[JournalLine], first: date, last: date) -> Decimal:
    """Debits minus credits at each line's recorded value, for lines dated in
    [first, last]. Callers choose the accounts."""
```

- `line.value` is the recorded `quantity × unit_price`, never a price read.
- A refund is a credit and reduces the figure, so a period can come out
  negative.
- Splits and reclassifications post their adjusting entries on the original
  entry's date (`splitting.py`, `classification.py`). The corrected spending
  therefore lands in the original period, and a reclassified line nets to
  zero in `Unclassified Expense`.

### 5.4 The report's pure functions

```python
@dataclass(frozen=True, slots=True)
class CappedAccount:
    name: str
    history: list[CapChange]            # oldest first
    covers: frozenset[int]              # §5.2

@dataclass(frozen=True, slots=True)
class BudgetRow:
    account: str
    period: Period
    spent: Decimal
    day: int | None                     # today's day number in the period, counting from 1, if it contains today

    @property
    def over(self) -> Decimal:          # signed: positive is overshoot
        return self.spent - self.period.cap

    @property
    def is_over(self) -> bool:
        return self.spent > self.period.cap

@dataclass(frozen=True, slots=True)
class BudgetReport:
    rows: list[BudgetRow]               # by account name, then period start
    unclassified: Decimal               # 080
    uncapped: Decimal                   # 080

def period_rows(capped: Sequence[CappedAccount], lines: Sequence[JournalLine],
                state_on: Callable[[date], str], start: date, end: date, today: date) -> list[BudgetRow]

def in_force(history: Sequence[CapChange], day: date) -> Cap | None:      # 080
    """The cap in force on `day`; None before the first entry or under an end entry."""

def uncapped_spent(capped: Sequence[CappedAccount], cappable: AbstractSet[int],
                   lines: Sequence[JournalLine], start: date, end: date) -> Decimal   # 080
```

- **`period_rows`** filters each capped account's lines by `covers` once. For
  each shown period it computes `net_spent` over the period's own dates, not
  the range's. Rows come in `capped` order, which is by name, and periods in
  date order.
- **`uncapped_spent`** keeps lines on `cappable` accounts dated in
  `[start, end]` with no capped account `c` where `line.account_id in
  c.covers` and `in_force(c.history, line date) is not None`. It then
  returns their `net_spent`.
  - "In force" comes from the history, not from the shown periods. That is
    the spec's "no cap in force … on the line's date".
  - Covers contain descendants, so covers containing the account is the
    spec's "on itself or on any ancestor".
- **The unclassified row** is `net_spent` of the lines in
  `BudgetAccounts.unclassified`, dated in `[start, end]`.
- **`in_force` is a reverse linear scan.** A history has a handful of
  entries, so `bisect` would be noise.
- **These are the spec's "pure functions of the cap history, the Bundesland
  history, the range and the lines".** The Bundesland arrives as `state_on`,
  as in CS §7.2. The lines are `JournalLine` rows that tests build as
  transient objects, as `test_sampling.py` does.

### 5.5 No spending hides

With `--to ≤ today`, every line on a cappable account dated in
`[--from, --to]` is in a shown period, in the uncapped row, or both. Take a
line covered on its date d by some cap. That cap has a period containing d,
because periods tile each in-force span. The period starts on or before
`d ≤ --to ≤ today`, and it overlaps the range because it contains d, so it
is shown. A line on `Unclassified Expense` is in its own row only. A line on
a child of two capped ancestors counts toward both, which is "checked
independently".

---

## 6. Decision 3: output layouts

### 6.1 `list-caps`

```
account          from        cap  rule
---------------  ----------  ------  ------------------------------
Groceries        2026-01-01  300.00  day 1
Groceries        2026-03-10  400.00  day 1
Insurance        2026-03-01  480.00  yearly 03-01
Restaurants      2026-01-01  150.00  workday 25
Restaurants      2026-07-01       -  no cap
Rundfunkbeitrag  2026-01-01   55.08  every 3 months from 2026-01-15
```

- **One table for all accounts,** grouped by account name, each history
  oldest first. The spec asks for "every account's full history, oldest
  first".
- **Each row reads as the command that recorded it**
  (`set-cap Groceries 400 "day 1" --from 2026-03-10`), which is the
  `list-states` precedent (CS §5.2).
- **An end entry shows `-` for cap**, through `missingval`, and `no cap`
  for rule. "No cap" is the spec's own phrase. A cap of 0 shows `0.00`, so
  the two never look alike.
  - The `-` comes from `None`, never from a string: a string in a numeric
    column turns off `floatfmt` for the whole column (the note in
    `balance_cmd`).
- **No "in force today" marker.** It would make a listing of ledger data
  depend on the clock (CS §5.2).
- **Empty:** ``No caps; set one with `kohle-cli set-cap <account> <amount> "<rule>" --from YYYY-MM-DD` ``,
  exit 0. This is the `list-states` precedent.

### 6.2 `budget`

With today 2026-10-30, the default range is 2026-01-01 to 2026-10-30. Rows
for April to September are omitted here:

```
account               from        to             cap    spent    over/under  note
--------------------  ----------  ----------  ------  -------  ------------  ------------------------------
Groceries             2026-01-01  2026-01-31  300.00   320.50         20.50  over
Groceries             2026-02-01  2026-02-28  300.00   251.20        -48.80  -
Groceries             2026-03-01  2026-03-09  300.00   112.00       -188.00  short
Groceries             2026-03-10  2026-03-31  400.00   289.90       -110.10  short
Groceries             2026-10-01  2026-10-31  400.00   371.15        -28.85  partial day 30 of 31
Insurance             2026-03-01  2027-02-28  480.00   492.00         12.00  over, partial day 244 of 365
Restaurants           2026-06-25  2026-06-30  150.00    41.00       -109.00  short
Rundfunkbeitrag       2026-01-01  2026-01-14   55.08     0.00        -55.08  short
Rundfunkbeitrag       2026-10-15  2027-01-14   55.08     0.00        -55.08  partial day 16 of 92
Unclassified Expense  2026-01-01  2026-10-30       -    84.10             -  -
(uncapped)            2026-01-01  2026-10-30       -   612.40             -  -
```

- **The columns are the spec's,** in its order: account, period start and
  end, cap, spent, and signed over/under.
- **The marks share one column, `note`, which is last.** Its values contain
  spaces. As the last column they cannot move the figure columns for a
  whitespace-split reader, which is the reason CS §5.3 gave for putting
  `role` last. `-` means no note (CS §17 item 1).
- **The note parts come in a fixed order, joined by `, `:** `over` when
  spent > cap, then `short`, then `partial day N of M`. `over` comes first
  because overshoot is what the report is for. An overshoot inside the
  current partial period is still marked, because a deviation is
  information.
- **No `+` sign on overshoots.** tabulate parses `"+20.50"` as a number and
  reformats it, so the sign would need `disable_numparse` on that column.
  Negative means under, and the header says which way round it is.
- **Row order.** Accounts by name, then periods by start, then the two
  summary rows. Grouping by account reads like a per-category ledger and
  copes with mixed rhythms (monthly beside yearly) better than a
  chronological interleave.
- **The `Unclassified Expense` and `(uncapped)` rows are always present,**
  even at 0.00 and before `Unclassified Expense` exists. A visible zero is
  what makes "spending cannot hide" checkable at a glance.
  - Their `from` and `to` are the range.
  - Cap, over/under and note are `None`, which renders `-`.
  - **`(uncapped)` carries parentheses** so it cannot be read as an account
    named "uncapped".
- **One table, not a second table for the two summary rows.** `spent` then
  stays one aligned column, and a test can parse every row the same way.
- **No caps at all** prints the two summary rows alone. No special message
  is needed.

### 6.3 `budget --from/--to`

- `--to` defaults to today and `--from` to 1 January of `--to`'s year.
- `click.DateTime(formats=["%Y-%m-%d"])`, as in `net-worth-history`.
- **`--to` after today is a usage error,** as in `net-worth-history`, and so
  is `--from` after `--to`. Both exit 2 before any session opens.
  - Consistency with the other date-ranged report.
  - With `--to ≤ today`, §5.5's no-hiding argument holds. With a future
    `--to`, a future-dated line under a cap whose period starts after today
    would be in no shown period and not uncapped either.
  - The spec's "periods that start after today are not shown" still holds
    inside the use case (§4.3). §15 item 7 records this reading.

### 6.4 Confirmations

- `set-cap`: `Set cap on Groceries from 2026-03-10: 400.00, day 1`. It is the
  same after an identical no-op, as for `set-setting` and `move-state`.
- `end-cap`: `Ended cap on Groceries from 2026-09-01`.

---

## 7. Modules

### 7.1 `kohle/use_cases/recurrence.py` (074, 076, 077)

§2. It stays pure, with no storage and no roles, and it still knows nothing
of caps.

### 7.2 `kohle/use_cases/budgeting.py`

Everything in §4–§5, plus the four use cases (§8).

- **One module, as `sampling.py` and `bundesland.py` are:** the pure
  functions beside the `UnitOfWork`s that use them. At about 300 lines it
  does not need splitting.
- **Not in `reporting.py`.** Its docstring scopes it to "reports that read
  prices". `budget` must read none, and the price guard should cover it as it
  covers `journal.py` (§16.6).
- **Import direction.** It may import `journal.py` (`PEOPLE_ROOT`,
  `UNCLASSIFIED_EXPENSE`, `account_lines_service` through services),
  `bundesland.py` (`state_lookup`) and `recurrence.py`. `journal.py` must
  never import it. That is the rule `classification.py` and `splitting.py`
  follow.

### 7.3 `kohle/services/cap_services.py` (075)

These mirror `state_services.py` one for one:

```python
@crud_retrieve
def list_cap_entries_service(ctx) -> Result[list[CapEntry], CapError]
    # every entry, account eager-loaded (the session closes before the CLI reads it),
    # accounts by name, each history oldest first

@crud_create
def _create_cap_entry_service(ctx, account_id: int, effective_from: date,
                              amount: Decimal | None, rule: str | None) -> Result[CapEntry, CapError]

@crud_update
def _update_cap_entry_service(ctx, entry_id: int, amount: Decimal | None, rule: str | None) -> Result[CapEntry, CapError]

def put_cap_entry_service(ctx, account_id: int, effective_from: date,
                          amount: Decimal | None, rule: str | None) -> Result[CapEntry, CapError]:
    """Create the entry for (account, effective_from), or replace it. The same
    amount and rule write nothing, so a replay leaves no OperationGroup."""
```

- Infrastructure errors map to `CapError(str(err))`, as `StateError` does.
- `Decimal('300') == Decimal('300.00000000')`, so a value read back from
  `QUANTITY` compares equal to the typed one, and the no-op check works.

---

## 8. Use cases

### 8.1 `SetCap` (075)

```python
class SetCap(UnitOfWork[CapEntry, CapWriteError]):
    def execute(self, account_name: str, amount: Decimal, rule: str, effective_from: date) -> Result[CapEntry, CapWriteError]
```

1. **Before the transaction:** `if not amount.is_finite() or amount < 0`,
   return `InvalidCapAmount`. `is_finite` comes first because comparing a
   NaN raises `InvalidOperation`, and `DecimalParamType` accepts `NaN` and
   `Infinity`.
2. `parse_recurrence(rule)`. An `Err` passes through unchanged. Then
   `canonical = render_recurrence(…)`.
3. **Inside `_run`:** `budget_accounts`, then `check_cappable(name)`, then
   `put_cap_entry_service(ctx, account.id, effective_from, amount, canonical)`.

The pure checks run first and open nothing, which is `SetSamplingRules`'s
order. Any failure writes nothing, so `list-caps` and the `operations` count
stay unchanged.

### 8.2 `EndCap` (079)

```python
class EndCap(UnitOfWork[CapEntry, CapWriteError]):
    def execute(self, account_name: str, effective_from: date) -> Result[CapEntry, CapWriteError]
```

Inside one `_run`:

1. `budget_accounts`, then `check_cappable`. An unknown or uncappable account
   gets the same message as in `set-cap`.
2. Take this account's entries from `list_cap_entries_service`. `latest` is
   the last one with `effective_from ≤ D`.
3. Refuse with `NoCapInForce(name, D)` if `latest` is missing, or if it is an
   end entry dated before D.
4. Otherwise `put_cap_entry_service(ctx, account.id, D, None, None)`.

The rule is "a cap is in force on D before this write":

- **A cap entry at D itself is replaced by the end entry.** With no delete
  command, that is how a mistaken `set-cap` at D is withdrawn.
- **An identical end entry at D writes nothing and succeeds,** like every
  other replay.
- **No cap in force, or an earlier end entry,** gives `NoCapInForce`.
  Recording "no cap" over a span that already has none would only add a cut.

### 8.3 `ListCaps` (075)

It wraps `list_cap_entries_service`. It only reads, so it leaves no group.

### 8.4 `QueryBudget` (076, grows in 077 and 080)

```python
class QueryBudget(UnitOfWork[BudgetReport, BudgetError]):
    def execute(self, start: date, end: date, today: date) -> Result[BudgetReport, BudgetError]
```

Inside one `_run`:

1. `budget_accounts(ctx)`.
2. `list_cap_entries_service(ctx)`, grouped by account and parsed into
   `CapChange`s with `parse_recurrence`. A stored rule that fails to parse
   can only come from a hand-edited ledger. Its `InvalidRecurrence`
   propagates, as in `current_sampling_rules` (CS §7.2).
3. For each capped account, `descendant_account_ids_service`, minus
   `unclassified` from 080, gives a `CappedAccount`.
4. `list_state_entries_service`, then `state_lookup`, then the refusal (§4.5),
   then `state_on`.
5. One `account_lines_service` call over the union of all covers, plus the
   cappable and unclassified ids from 080.
6. `BudgetReport(period_rows(…), net_spent(unclassified lines in range),
   uncapped_spent(…))`.

- **`today` is a parameter,** as in `ValuedNetWorth.execute(today, …)`. The
  use case reads no clock, and tests need no patching below the CLI.
- **One read of all the relevant lines,** not `query_lines_by_period_service`
  per account and period. The spec's "the report reads from there" means the
  journal lines `entries-in-period` reads. This is the multi-account sibling
  service, and it avoids N×M queries.
- **It reads only through `crud_retrieve`,** so it leaves no
  `OperationGroup`. It touches no price module.

---

## 9. CLI (`kohle/app/cli/cli.py`)

| Command | Arguments | `writes` | Output |
|---|---|---|---|
| `set-cap` | `ACCOUNT AMOUNT RULE`, `--from YYYY-MM-DD` (required) | `True` | §6.4 |
| `end-cap` | `ACCOUNT`, `--from YYYY-MM-DD` (required) | `True` | §6.4 |
| `list-caps` | | `False` | §6.1 |
| `budget` | `--from`, `--to` | `False` | §6.2 |

- **`--from` on `set-cap` and `end-cap`** is `click.DateTime(formats=["%Y-%m-%d"])`
  with `.date()`, not `EFFECTIVE_FROM`, which also takes `start`. A bad date
  is a usage error (exit 2) that opens no session.
- **`AMOUNT` is `DECIMAL`.** A non-number is a usage error.
- **A negative amount needs `--`, and `--from` must come before it.**
  Click reads `-5` as an option (`No such option: -5`, exit 2). Measured:
  `set-cap --from 2026-01-01 Groceries -- -5 "day 1"` reaches
  `InvalidCapAmount`, and `set-cap Groceries -- -5 "day 1" --from …` does
  not, because `--from` after `--` is positional. Both forms write nothing,
  which is what the spec asks. The tests use the first form to reach the
  domain error.
- **`RULE` is one plain argument,** and the user quotes it. An unquoted rule
  is "too many arguments", exit 2.
- **The account goes through `check_cappable`, not `click.Choice`.** It
  reaches the same `UncappableAccount` text whether it comes from the CLI or
  a later TUI. AI §10 gives the same reason for `set-setting KEY`.
- **`budget`** takes `today = date.today()` with the `DTZ011` noqa that
  `net-worth-history` uses. It validates the range (§6.3) and calls
  `QueryBudget(make_session()).execute(start, end, today)`. It renders with
  `tabulate(rows, headers="keys", floatfmt=".2f", missingval="-")`.
- **Each `Err` becomes a `ClickException`** (exit 1).
- **Every new command declares `writes`,** so the reader refusal applies to
  `set-cap` and `end-cap` before their bodies run (DT).

---

## 10. Errors (`kohle/domain/domain_errors.py`)

| Class | Fields | Message | Slice |
|---|---|---|---|
| `CapError(Exception)` | | base; also wraps infrastructure failures | 075 |
| `UncappableAccount(CapError)` | `name, problem, cappable: list[str]` | `cannot cap {name!r}: {problem}; accounts that can be capped: {", ".join(cappable)}`. With no cappable account: ``cannot cap {name!r}: {problem}; no account can be capped yet, add an expense account with `kohle-cli add-account <name>` `` | 075 |
| `InvalidCapAmount(CapError)` | `amount` | `invalid cap amount {amount}; expected a number of 0 or more` | 075 |
| `NoCapInForce(CapError)` | `name, on: date` | `{name} has no cap in force on {on}; list-caps shows its history` | 079 |

`problem`, by the check that failed (§5.1):

| Check | `problem` |
|---|---|
| Missing | `no such account` |
| In `Unclassified Expense`'s subtree | `it has its own row in budget` |
| Under `People` | `it is a person under People` |
| Not of expense type | `it is an {type} account` |

`expected` for `InvalidRecurrence` is the table in §2.3. The class is
unchanged.

Unions:

- `CapWriteError = CapError | AccountError | InvalidRecurrence`
- `BudgetError = CapError | AccountError | JournalError | InvalidRecurrence | StateError`

---

## 11. README and AGENTS.md

### 11.1 README

| Section | Change | Slice |
|---|---|---|
| Net worth over time → Sampling rules | The `every` and `yearly` rows lose "Specified, not built yet". Add their meanings: in both directions from A; month dates clamp without drift; `yearly 02-29` lands on 28 February; neither shifts; no `years` unit; N 1–999; plural units. That statement becomes false in 074, so 074 removes it (CS §15 item 4). | 074 |
| Net worth over time → Sampling rules | `set-sampling-rules` accepts the two kinds, with a fortnightly salary as the example | 081 |
| New "Budgeting" section after "Net worth over time" | Command names are provisional. Caps: an effective-dated history per expense account, in the base currency, leaf or parent, what is refused. `set-cap`, `end-cap`, `list-caps` with the §6.1 example. How periods form: from occurrence to the day before the next, all seven kinds, payday to payday, cut at D, short, no prorating, and why `day 1` rather than `last day` gives calendar months. `budget` with the §6.2 example: shown whole, partial, the note column, the two summary rows, no rollover, `--from`/`--to` defaults and the after-today error. It reads no prices. | 081 |

The vocabulary table stays under "Sampling rules", and the Budgeting
section links to it. Moving the table to a section of its own would be a
README restructure that neither issue asks for.

### 11.2 AGENTS.md (081)

Replace the Bundesland sentence in Context with:

> The Bundesland is not a setting: it is an effective-dated history in
> `state_entries`; spending caps are an effective-dated history per expense
> account in `cap_entries`; and the net-worth-history sampling rules are a
> stored list in `sampling_rule_lists`.

After the `reporting.py` sentence, add:

> `budget` reads no prices; it lives in `kohle/use_cases/budgeting.py`,
> which the price guard covers like `journal.py`.

The second sentence keeps a later agent from putting `budget` into
`reporting.py`.

---

## 12. The decision categories

### State and data lifecycle

- **`set-cap` and `end-cap`.**
  - The amount and rule are validated before the transaction, and the account
    and the in-force rule inside it.
  - The write is one `INSERT` or one `UPDATE`, so it is atomic by
    construction.
  - It records one `Operation`, or none for an identical entry.
- **Reversible only by hand.** There is no delete. A correction overwrites
  the earlier values of that D, which are not kept (§3.1).
- **Auditable.** `list-operations` names `cap_entries` and the row id.
  `list-caps` shows the history as it stands. The values before a correction
  are lost, as for every update in the codebase.
- **Replayable.** Every `list-caps` row reads as the command that recorded
  it, and replays are no-ops.
- **An entry identical to the one before it is recorded but changes no
  period** (§4.1). The history stays a faithful record of what was typed.
  The tiling is what makes a correction harmless.
- **Nothing derived is stored.** Periods, spending and attribution are
  recomputed on every run from the history, the Bundesland history and the
  lines. So a new cap entry, a classification correction, a split or a
  `move-state` all show up on the next run with no invalidation step.
- **074 adds no migration** (§2.5). 075's migration is all-or-nothing under
  `migrate`'s staging (AI §5.5). Its downgrade refuses while caps exist.
- **Reads (`list-caps`, `budget`)** use `crud_retrieve` only, so they leave
  no `OperationGroup`.
- **Snapshots and readers carry `cap_entries` unchanged,** like any other
  ledger table. It never goes near `config.toml`.

### Error propagation

- **`recurrence.py`** returns `InvalidRecurrence`, a pure value that knows
  nothing of caps.
- **`budgeting.py`'s pure functions are total.**
  - `cap_periods`, `period_rows`, `uncapped_spent` and `net_spent` return
    values, not `Result`s.
  - Every refusal belongs to an input. It happens before they are called:
    `check_cappable`, the amount check, `parse_recurrence`, and the
    Bundesland refusal over the parsed history. This is the
    `sample_dates`/`state_lookup` split from CS §7.2.
- **`cap_services.py`** turns infrastructure failures into `CapError(str)`,
  so nothing above it sees SQLAlchemy.
  - A concurrent second `set-cap` on the same account and new D fails on the
    `UNIQUE` and is reported as a `CapError`, with nothing written.
- **The use cases** return the §10 unions.
  - They pass `InvalidRecurrence`, `AccountError` and `NoStartState` through
    without re-wrapping, because each message already names the user's next
    step.
- **The CLI** turns `Err` into `ClickException` (exit 1). Click usage errors
  (dates, `AMOUNT`, the range, a stray `-5`) exit 2 before any session
  opens.
- **What each layer knows.**
  - `recurrence.py`: no caps, no storage.
  - `budgeting.py`: caps, periods and the account partition, but not tables
    or rendering.
  - Only the CLI knows `-`, `no cap`, `(uncapped)`, the note words and the
    column names.

### Concurrency and ownership

- **Every `kohle-cli` process is single-threaded,** with no shared mutable
  state of its own. Processes are serialised by SQLite's locking and the busy
  timeout (DT §5).
- **The generators in `recurrence.py` are local to each call.**
  `_public_holidays`' cache is still the one piece of process-global mutable
  state. CS §13's note for `tui-wiring` applies unchanged: guard it, or run
  reports on one worker.
- **`budget`'s reads are not one snapshot** (DT §5.2): accounts, then caps,
  then states, then lines. A `set-cap` that commits mid-report can mix that
  one write's before and after in that run. Every existing report already has
  this property, and a re-run is consistent.
- **`set-cap` and `end-cap` on the same (account, D) race on the `UNIQUE`.**
  One wins and the other reports a `CapError`.

### Reuse

Used, not reimplemented:

- `recurrence.py`, extended in place. It stays the one vocabulary.
- `state_lookup`, `list_state_entries_service` and `NoStartState`.
- `descendant_account_ids_service` (the subtree), `list_accounts_service`,
  `get_account_by_name_service` and `account_lines_service`.
- `PEOPLE_ROOT` and `UNCLASSIFIED_EXPENSE` from `journal.py`.
- `put_state_entry_service`'s create, update or no-op shape, for
  `put_cap_entry_service`.
- `balance_sheet_accounts`' shape, for `budget_accounts`.
- `UnitOfWork` and the `crud_*` decorators.
- `_KohleCommand(writes=…)`.
- `DECIMAL`, `click.DateTime`, and tabulate with `floatfmt=".2f"` and
  `missingval="-"`.
- `_refuse_if_unrepresentable`.
- `test_reader`'s argv tables and the price guard's lists.

Introduced for the next piece of work:

- **`next_occurrence`** gives due dates for `expected-payments`.
- **`cap_periods` for `savings-targets`.** That brief asks for the same
  effective dating, cut at D, no rollover and no prorating. `cap_periods`
  depends only on each entry's date and rule; the amount is carried along.
  When targets land, lift its input to `(effective_from, recurrence | None)`
  pairs and return periods indexed into the caller's history, so each
  feature keeps its own payload. It is not generic now, because it has one
  consumer.
- **`budget_accounts`** is the single definition of "an account whose
  spending is budgeted".

### Extension points

- **Recurrence kinds** stay a closed sum. A new kind needs a dataclass, a
  parse production, a `KINDS` entry, a render case and an `_ascending` case.
  `occurrences`, `next_occurrence`, periods and sampling then follow. CS's
  contract holds:
  - parsing then rendering is the identity on canonical text;
  - the output is ascending;
  - a kind that does not shift never calls `state_on`;
  - stored text is user syntax, so a new kind needs no migration.
- **`cli-command-naming`** may rename the four commands. The use cases do not
  know the names, and the only places they appear are the CLI and the
  messages that point to commands (`UncappableAccount`, the empty
  `list-caps` text).
- **A TUI** gets periods, partial days, the over flag and both summary
  figures from `QueryBudget`. Only rendering is left in the CLI.
- **No plugin point is introduced.** Nothing in the spec asks for one.
  Alerts, cron and machine-readable output are non-goals.

### Build vs. buy

| Component | Decision | Evaluated, and what it could not do |
|---|---|---|
| `every` / `yearly` arithmetic | **Build:** `calendar`, ordinals and month indices | `dateutil.rrule` (pinned): forward from `DTSTART` only; skips where the spec clamps (`BYMONTHDAY=31`, `02-29`); no holiday shift. `dateutil.relativedelta` (pinned): clamps correctly, but it is no shorter and gives no first index on or after `start` (§2.1). |
| Rule parser | **Build:** extend the `match` over tokens | `pyparsing` (pinned): CS's reasons stand, since each error must name the bad part and the choices. |
| Period builder, attribution | **Build** | No library has these semantics: they are this spec's. |
| Storage | **Build:** one table | The `settings` table is a key/value channel (§3.1). |
| Subtree, lines, account lookup | **Reuse** the existing services | |
| Effective-dated lookup | **Reuse** `state_lookup` for states; a three-line reverse scan for caps | `bisect` is not worth it for a handful of entries. |
| Table output | **Buy:** tabulate, already used | |

### Abstractions introduced

| Abstraction | Forcing problem |
|---|---|
| `Every`, `Yearly` | Rendering back to what the user typed, and per-kind arithmetic, for two kinds the spec adds. |
| `Monthly` alias | `_unshifted` only has meaning for month-based kinds, and its `assert_never` must stay exhaustive. |
| `_ascending` | The first occurrence after a date for kinds with no fixed gap (`next_occurrence`), and one walk per kind instead of a month walk with slack. |
| `next_occurrence` | Where a period ends. |
| `shifts` made public | The conditional Bundesland refusal (§4.5). |
| `CapEntry` | Storage (§3). |
| `Cap`, `CapChange` | The pure functions need parsed rules, but the row holds text, so parse once. `cap: Cap \| None` makes "an amount and a rule, or neither" structural, not two loose optionals. |
| `Period`, `BudgetRow`, `BudgetReport` | ORM rows cannot cross the session boundary (the `UnclassifiedLine` precedent), and the report has computed fields: short, the day number, over. |
| `CappedAccount` | The pure functions need each capped account's name, history and covered ids together. Three parallel dicts would drift. |
| `BudgetAccounts`, `budget_accounts`, `check_cappable` | Three use cases share one partition, and each refusal must name its reason (§5.1). |
| `CheckConstraint` on `cap_entries` | Readers branch on `amount is None` and parse `rule` otherwise. |
| The errors in §10 | Each is a distinct user message. |

**Deliberately not introduced:**

- a generic "plan" or "target" engine;
- a `Protocol` for history entries shared between `StateEntry` and `CapEntry`;
- a `previous_occurrence` primitive;
- a `CapHistory` class;
- a money type;
- a separate end-cap table, or a `kind` column;
- a period cache.

---

## 13. Alternatives rejected

- **RRULE or `dateutil` as the internal form.** §2.1.
- **A month-based generator with a slack month, kept as is, plus a separate
  `next_occurrence` per kind.** It needs two walks per kind, and a guessed
  window for kinds with an unbounded gap. The single generator replaces both
  (§2.4).
- **Unbounded N.** `date` overflows on the first boundary past 9999-12-31
  (§2.3).
- **Singular units (`every 1 month`), or accepting both spellings.** One
  spelling per kind (CS §4.1).
- **Caps in the `settings` table,** or a generic effective-dated key/value
  table. Both would make a general channel (§3.1).
- **One row per cap with `valid_from`/`valid_to`.** Every change would be two
  writes (close the old row, open a new one), which is two `Operation`s.
  Replacing a D would become range surgery.
- **Append-only entries, like `sampling_rule_lists`.** Every read would need
  "latest per (account, D)", the max-per-key subquery AI §15 rejected. The
  dated history is already the record, and `state_entries` updates in place.
- **A separate end-cap table, or a `kind` column.** A separate table could
  not hold "one entry per (account, D)" across both kinds, and a `kind`
  column duplicates the NULL pair.
- **Storing the parsed rule (JSON).** It couples storage to class names (CS
  §14).
- **Amounts as integer cents.** It would be a second money representation;
  journal amounts are `QUANTITY`.
- **Refusing amounts with more than two decimals.** Lines can carry sub-cent
  values anyway (`record` accepts any decimal), so it would not remove the
  rounding display edge.
- **`--from start` for caps.** A period starting in year 1 means nothing.
- **Accepting `--to` after today.** §6.3.
- **Refusing `budget` with no Bundesland unconditionally,** as
  `net-worth-history` does. The spec ties the refusal to the shifting kinds,
  and a `day 1`-only ledger needs no calendar. This form survives only inside
  076 (§14).
- **Refusing `set-cap` with a shifting kind when there is no Bundesland.** It
  makes the order of two commands matter (CS §14).
- **`budget` in `reporting.py`.** §7.2.
- **`query_lines_by_period_service` per account and period.** N×M queries.
  One `account_lines_service` read does the same job.
- **Computing subtrees in Python from `parent_id`.** It duplicates the
  cycle-safe CTE.
- **Generating periods from `--from`.** §4.2.
- **Clipping periods to the range.** The spec forbids it.
- **Counting `People` accounts of expense type as spending.** They are
  receivables, and the spec refuses caps on them.
- **Letting a capped parent count lines in `Unclassified Expense`.** The spec
  says such a line appears only in the unclassified row.
- **Marking over, short and partial in three columns.** That makes the table
  wider for flags that are mostly empty.
- **A `+` sign on overshoots.** §6.2.
- **A blank label for the uncapped row, or a second table for the two
  summary rows.** §6.2.
- **`list-caps` marking the entry in force today.** §6.1.
- **Showing caps in `list-settings`.** They are not settings (CS §6).
- **An `end-cap` that succeeds with no cap in force.** It would record a cut
  with nothing to end.
- **Cutting at an entry identical to the one before it,** which is the
  spec's literal wording. With no delete and no prorating, correcting a
  mistaken D would give each short half of the period the full cap. The
  user chose the collapse instead (§4.1, §15 item 1).
- **Refusing an identical entry in `set-cap`.** Recording the previous cap
  at a mistaken D is the only correction path, so it must be accepted.
- **Collapsing in `put_cap_entry_service`,** by deleting or skipping the
  row. The audit trail and `list-caps` would no longer show what was typed,
  and a later change to the entry before it would silently change what the
  skipped row means.

---

## 14. Slice order and per-slice files

**The order is unchanged:** 074 → 075 → 076 → 077 → 078 → 079 → 080 → 081.
075 does not depend on 074. Landing 074 first means `set-cap` accepts all
seven kinds from the start, so do that.

**What moves between the issues.** The period builder is one loop over the
history, and the account partition is one function. Splitting either along
the issue lines would mean writing code that a later slice deletes. So:

1. **076 builds the whole tiling, including the cut at D.** 075 already lets
   a user record two entries for one account, so a 076 that ignores the
   second one would be wrong, not just incomplete.
   - 078 keeps the `short` flag, its mark, the identical-entry collapse
     and the cut tests.
2. **076 builds periods for every kind mechanically,** because they come
   from `next_occurrence`.
   - 076 refuses whenever there is no `start` entry.
   - 077's production change is narrowing that refusal to the shifting kinds
     (§4.5). Its tests prove the six other kinds.
   - Issue 076's "this slice covers `day N` periods" is then about what it
     tests, not about what it refuses.
3. **075 ships `put_cap_entry_service` whole: create, update and no-op.** A
   create-only 075 would surface a raw `UNIQUE` failure for a repeated D
   until 078. 078 keeps the replace test and adds its `budget` consequence.
4. **Each slice removes the README statements its change makes false** (CS
   §15 item 4). That means only 074's vocabulary rows. 081 writes the
   Budgeting section.
5. **No review stop is needed inside the run.** Every slice leaves a
   coherent, tested state.

### 074: `every` and `yearly`

- **First,** before touching `recurrence.py`, capture
  `tests/fixtures/occurrences_monthly_kinds.txt` from the current
  `occurrences` (§16.1).
- **Production (`recurrence.py`):**
  - `Every`, `Yearly`, `Monthly`;
  - the `KINDS` entries;
  - the parse productions, errors and render cases;
  - `_ascending`, with `occurrences` rebuilt on it.
- **Tests:** `test_recurrence.py` (§16.1), `test_sampling_cli.py` (§16.4),
  and the existing `test_pre_feature_equivalence.py`, unchanged.
- **README:** the vocabulary rows (§11.1).

### 075: `set-cap` and `list-caps`

- **Production:**
  - `models.py`: `CapEntry`;
  - the migration, and `HEAD_REVISION`;
  - `cap_services.py`;
  - `budgeting.py`: `BudgetAccounts`, `budget_accounts`, `check_cappable`,
    `SetCap`, `ListCaps`;
  - errors: `CapError`, `UncappableAccount`, `InvalidCapAmount`;
  - CLI: `set-cap`, `list-caps`.
- **Tests:**
  - `test_budgeting.py` (partition);
  - `test_budgeting_cli.py` (§16.4);
  - `test_reader.py`: add `set-cap` to `_WRITE_ARGV` and `list-caps` to
    `_read_argv`;
  - `test_price_guards.py`: `budgeting.py`, `cap_services.py` and both
    callbacks;
  - `test_migration_downgrade.py`: `BEFORE_CAP_ENTRIES = "a7c3e9d5b124"`.

### 076: `budget` for a capped account

- **Production:**
  - `recurrence.next_occurrence`;
  - `budgeting.py`: `Cap`, `CapChange` (with `cap: Cap`), `Period` (no
    `short`), `CappedAccount`, `BudgetRow`, `BudgetReport` (rows only),
    `cap_periods`, `net_spent`, `period_rows`, and `QueryBudget` with the
    unconditional `start` refusal;
  - CLI: `budget`, with `over` and `partial` in the note.
- **Tests:**
  - `day 1` periods, net spending, refunds, a negative period, parent and
    child independence;
  - shown whole, nothing after today, partial `day N of M`;
  - no group, no price call (§16.6);
  - `test_reader.py`: `budget`.

### 077: every kind as a period boundary

- **Production:** `shifts` public, and the conditional refusal (§4.5).
- **Tests:**
  - `workday 25` payday to payday, including across a move;
  - `every 1 months from 2026-01-31` and `yearly 02-29` periods;
  - `every`/`yearly` never shift (a `state_on` that raises);
  - the refusal with a `workday` cap and no `start`;
  - a `day 1`-only budget with no `start` succeeds.

### 078: cut at D

- **Production:**
  - `Period.short` and the `short` mark;
  - the identical-entry collapse in `cap_periods` (§4.1, user-approved).
- **Tests:**
  - the spec's two cut examples;
  - a natural boundary is not short;
  - an entry identical to the one before it cuts nothing. 300 `day 1` from
    01-01, re-set to 300 `day 1` from 03-10, leaves March one full period at
    300. `list-caps` still shows both entries, and the re-set is one
    `Operation`;
  - A, B, A cuts at both changes;
  - a repeated D is one `update` `Operation`, and `budget` shows the new
    values;
  - a future D shows in `list-caps` and not in `budget`.

### 079: `end-cap`

- **Production:**
  - `CapChange.cap` becomes optional, and `cap_periods` skips end spans;
  - `EndCap`, `NoCapInForce`;
  - `list-caps` renders `-` and `no cap`;
  - CLI: `end-cap`.
- **Tests:** §16.4. `test_reader.py` and `test_price_guards.py` get
  `end-cap`.

### 080: the unclassified and uncapped rows

- **Production:**
  - `in_force` and `uncapped_spent`;
  - covers lose the unclassified subtree;
  - `QueryBudget` reads the cappable and unclassified lines;
  - `BudgetReport.unclassified` and `BudgetReport.uncapped`;
  - the CLI's two rows.
- **Tests:** §16.3, plus the existing `net-worth-history` suite unchanged.

### 081: docs

§11.

---

## 15. Gaps in the spec, and points for the user

**Status: resolved.** The user settled every item. Item 1 changed the
design. Items 2–13 are accepted as proposed.

1. **Resolved by the user: an entry identical to the one in force before it
   does not cut** (§4.1).
   - **The problem.** "An entry taking effect at D ends the running period
     on D−1" applied even when the entry repeats the one in force. The cap
     is not prorated, so each short half got the full cap. The likely
     trigger is fixing a mistaken D. Say
     `set-cap Groceries 400 "day 1" --from 2026-03-10` should have been
     04-01. The only repair is to re-set 300 at 03-10 and add 400 at 04-01.
     Under the literal rule, March became 03-01–03-09 and 03-10–03-31, both
     short at 300: 600 for the month. A mistaken `end-cap` repaired the same
     way had the same effect.
   - **The decision.** `cap_periods` drops an entry equal to the one
     immediately before it. This is a deliberate, user-approved refinement
     of the spec's cut-at-D wording, built in 078.
   - **Spec follow-up.** The spec text should be revised to match ("…
     unless it repeats the entry in force before it"). The user is raising
     that; no agent edits `dev/specs/`.
   - Removing entries still belongs to `undo-delete-edit`.
2. **A total cap needs the tree built up front.** "A total cap is a parent
   account the user creates and caps" works only for accounts created under
   that parent. There is no command to move an existing account. A leaf that
   gains a child can no longer be posted to, and an import whose rule points
   at it then fails. Today's root expense accounts cannot be gathered under a
   new total.
3. **`Unclassified Expense` under a capped parent.** The spec does not cover
   it. The design excludes that subtree from every cap, because "a line in
   `Unclassified Expense` appears only in the unclassified row" (§5.2). It
   arises only if the user created `Unclassified Expense` under a parent
   before the first import.
4. **The uncapped row counts only cappable accounts:** expense type, outside
   `People` and `Unclassified Expense`. The spec says "lines whose account
   had no cap in force" without naming a universe. Person accounts are
   usually of expense type (the `add-account` default) but are receivables.
5. **A capped parent counts its whole subtree, whatever the types** (an asset
   child included), which is the literal "subtree". Mixed-type subtrees are
   unusual.
6. **"Without a Bundesland entry they refuse" is read as `budget` refusing,
   and only when some cap entry uses a shifting kind.** `set-cap` accepts a
   shifting kind with no Bundesland (§4.5).
7. **`--to` after today is refused,** as in `net-worth-history`. The spec
   does not forbid a future `--to`. Its "periods that start after today are
   not shown" is then automatic, and the use case still enforces it for
   other callers (§4.3, §6.3).
8. **The design narrows the vocabulary.**
   - `every`'s N runs from 1 to 999 (§2.3). The sampling spec fixed the
     syntax with no bound.
   - Units are plural only.
   - `yearly` accepts one or two digits per field and refuses days that
     never exist (`02-30`).
9. **Issue 079's "the period running at D is cut at D−1 and marked short"**
   holds when D falls inside a period. When D is an occurrence of the ended
   rule, the previous period ended naturally on D−1 and is not short
   (§4.1).
10. **`end-cap` on a D that holds a cap entry replaces it with an end entry,**
    even when no cap was in force before D. That is the only way to withdraw
    a mistaken `set-cap` at D. An identical `end-cap` succeeds without
    writing. Any other `end-cap` with no cap in force gives `NoCapInForce`.
11. **Slice allocation** differs from the issues' wording in three places
    (§14). Every slice keeps a production change of its own, except that
    077's is only the narrowed refusal.
12. **The two summary rows are always shown,** at 0.00 when empty and before
    `Unclassified Expense` exists. The spec's "one row" is read as "always
    one row".
13. **Sub-cent amounts.** A cap or a line can carry more than two decimals.
    `over` compares exact values, while the table shows two decimals, so a
    0.004 overshoot reads `over` with `0.00`. This is accepted rather than
    restricting input `record` already allows.

---

## 16. Testing notes

### 16.1 `recurrence.py` (layer 1, pure, 074 and 076)

- **The oracle for the rewrite.** Before changing any code, the implementer
  runs the current `occurrences` from 2000-01-01 to 2040-12-31 for each of
  the 36 month-based rules of §2.4. It uses two histories: BY only, and BY
  with NI from 2026-01-01. The output goes to
  `tests/fixtures/occurrences_monthly_kinds.txt`, one line per rule and
  history. After the rewrite the test compares against that file. The old
  code is the oracle, as in CS §18.4. `test_pre_feature_equivalence.py`
  stays as it is.
- **Round trips:**
  - `every 2 weeks from 2026-01-02`;
  - `every 1 months from 2026-01-31`;
  - `every 24 months from 2026-01-01`;
  - `yearly 02-29`;
  - `yearly 2-9` → `yearly 02-09`;
  - `every 3 days from 2026-1-5` → `… from 2026-01-05`;
  - extra whitespace.
- **Errors, one per row of §2.3:**
  - `every 2 years from …`: names the units and months;
  - `every 1 month from …`;
  - `every 0 days from …` and `every 1000 days from …`;
  - `every x days from …`;
  - `every 2 weeks`, `every 2 weeks since 2026-01-01`;
  - `every 2 weeks from 2026-02-30` and `… from 20260101`;
  - `yearly 02-30`, `yearly 13-01`, `yearly 0229`, `yearly`;
  - the unknown-kind message lists all seven.
- **Occurrences:**
  - `every 3 months from 2026-01-15` contains 2025-10-15, in both
    directions;
  - `every 1 months from 2026-01-31` over Jan–Apr is 01-31, 02-28, 03-31,
    04-30;
  - `yearly 02-29` over 2027–2028 is 2027-02-28 and 2028-02-29;
  - `every 3 days from 2026-01-10` over 01-05..01-12 is 01-07 and 01-10;
  - `every 2 weeks from 2026-01-02` gives Fridays 14 days apart, before and
    after the anchor.
- **Never shift:** `every 1 days` over 2026-12-24..26 returns all three days,
  with a `state_on` that raises if called. The same holds for `yearly 12-25`.
- **`next_occurrence`** (076):
  - strictly after: on an occurrence it returns the next one;
  - `workday 25` across Christmas;
  - `every 999 months` far ahead without overflow.
- **Lazy import:** extend the subprocess check. A list made only of
  `every`/`yearly` rules leaves `holidays` out of `sys.modules`.

### 16.2 Periods (layer 1, `test_budgeting.py`)

- **All of §4.1's table.** The `short` flags and the identical-entry row
  arrive in 078.
- **Identical-entry collapse (078):** equal amounts written differently
  (`300` and `300.00`) collapse; a different amount, a different rule, or an
  end entry between two equal caps does not.
- **Shown:**
  - a quarterly period that starts before `--from` is kept whole;
  - a period starting after `min(--to, today)` is absent.
- **Partial:** the period containing today has `day = (today − start) + 1`;
  others have `None`.
- **Bundesland (077):**
  - payday-to-payday under `[START BY, 2026-01-01 NI]`;
  - the conditional refusal is tested at the use-case level (§16.5).

### 16.3 Attribution (layer 1, `test_budgeting.py`)

- **The partition (075):**
  - a person of type expense under `People` is not cappable;
  - neither is `Unclassified Expense`, nor an income account;
  - an expense parent is cappable;
  - the missing-account message lists the cappable names;
  - with no expense account, the message says how to add one.
- **Spending:**
  - 100 debit and 30 credit in one period gives 70;
  - a period with only a refund is negative;
  - a line on a child counts toward the parent's cap and the child's, each
    on its own.
- **Uncapped (080):**
  - a line on a child of a capped parent is not uncapped;
  - after an end entry from D, lines dated D or later are uncapped and
    earlier ones are not;
  - a line before a cap's first D is uncapped;
  - a line in `Unclassified Expense` is only in the unclassified figure, also
    when `Unclassified Expense` sits under a capped parent;
  - a person account's lines are in neither figure;
  - both figures cover exactly `[--from, --to]`.

### 16.4 CLI (layer 3, `test_budgeting_cli.py`)

**Setup.** Seed `People` with
`add-account People --type asset`, as `test_cli.py` does, since
`budget_accounts` requires it. Pin today with `test_portfolio_cli`'s
`_pin_today`.

- **`set-cap` (075):**
  - The spec's refusals write nothing and leave `list-caps` and the
    `operations` count unchanged:
    - `Unclassified Expense`, an income account, a People account, an
      unknown account;
    - an invalid rule;
    - `-5` through `set-cap --from 2026-01-01 Groceries -- -5 "day 1"`;
    - `NaN`.
  - Each message names the bad part and the choices.
  - A bad `--from` exits 2. An amount of 0 is accepted.
  - An identical repeat adds no group. A real set adds
    `create cap_entries <id>`.
  - A reader refuses it (through `test_reader`).
- **`list-caps`:** the empty message, the order, `-` with `no cap` (079), and
  `0.00` for a zero cap.
- **`budget` (076 onward):**
  - the default range;
  - `--to` after today and `--from` after `--to` exit 2 with no session;
  - columns and note words;
  - the spec's examples through the CLI;
  - the two summary rows always present (080).
- **`set-sampling-rules` (074):**
  - `salary: every 2 weeks from 2026-01-02` and `mid-month: yearly 12-24`
    are accepted and listed canonically;
  - `net-worth-history` gains rows on those dates;
  - an invalid `every` leaves `list-sampling-rules` unchanged.
- **`end-cap` (079):**
  - one `Operation`;
  - repeating the same D writes nothing;
  - with no cap in force, or for an unknown account, nothing is written and
    the message names the problem;
  - on a D that holds a cap, that entry is replaced.

### 16.5 Use case (layer 2)

- **Bundesland (077):** `QueryBudget` with a `workday 25` cap and no `start`
  entry returns `NoStartState`. With only `day 1` caps and no `start` entry
  it returns a report.
- **Counts:** after `budget`, the `operations` and `operation_groups` counts
  are unchanged.

### 16.6 Guards (`test_price_guards.py`)

- **AST guard:** add `kohle/use_cases/budgeting.py`,
  `kohle/services/cap_services.py`, and the callbacks of `set_cap_cmd`,
  `end_cap_cmd`, `list_caps_cmd` and `budget_cmd`.
- **Transitive import check:** add `kohle.use_cases.budgeting`.
- **Behavioural:** run `set-cap`, `list-caps`, `end-cap` and `budget` with
  the plugin loader patched to fail. The `prices` row count must stay the
  same. This is the spec's "calls no price plugin".

### 16.7 Migration (`test_migration_downgrade.py`, `test_schema_check.py`)

- The upgrade creates `cap_entries`, with the `UNIQUE` and the `CHECK`.
  Inserting an amount without a rule fails.
- A round trip with no caps works.
- The downgrade refuses with one entry and leaves the table in place.
- `HEAD_REVISION` is pinned.
