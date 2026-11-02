# Design: Richer classification rules

Spec: `dev/specs/complex-classification-rules.md` (frozen). Issues:
`dev/issues/082`–`089`.

Abbreviations: **EC** is `dev/design/expense-classification.md`, **CS** is
`dev/design/configurable-net-worth-sampling.md`, **BG** is
`dev/design/budgeting.md`, **DT** is `dev/design/device-topology-and-sync.md`.

**Upstream state this design assumes.**

- The spec is in `dev/specs/`, so this design treats it as frozen. The move
  out of `dev/inbox/` is not committed yet: git shows the inbox copy deleted
  and the spec and issues untracked.
- The spec's open questions take their defaults: `classify-rules` is a
  separate command over lines still in the unclassified buckets;
  `apply-rules` and `classify-rules` ask, with `--yes` to skip; `add-rule`
  gets no condition flags.
- §16 lists the points where the spec is silent, ambiguous, or at odds with
  the code. The design takes a position on each so it can be implemented,
  and the user should confirm or overrule them. Item 1 (`add-rule
  --priority`) and item 2 (duplicate rules already stored) are the ones
  that most need an answer.

---

## 1. Summary of the shape

| Concern | Decision | § |
|---|---|---|
| Tree storage | One `TEXT NOT NULL` column, `rules.condition`, holds the canonical one-line TOML inline table of the rule's `when`. Plus a nullable `rules.note`. `pattern` is dropped. `account_id` stays a foreign key. | 2 |
| Migration (082) | Each rule, retired ones included, becomes `{ any_field = <pattern> }` with the same id, priority and account. Downgrade works when every rule is still a single `any_field` with no note, and refuses otherwise. | 2.4 |
| Condition language | A pure module, `kohle/use_cases/conditions.py`. `When` is one frozen dataclass with one optional field per TOML key, so structural equality is content identity. It is parsed from what `tomllib` returns (`parse_float=Decimal`) and compiled to short-circuiting closures. | 3 |
| TOML writing | **Build:** a canonical renderer of about 60 lines. tomli-w cannot produce the spec's layout, and tomlkit is a second TOML parser with no exact-decimal value type. | 3.4, 13 |
| Identity | A file rule keeps a live rule's id when `(when, account_id)` are structurally equal. The note and the priority are the only fields an apply may update. | 5 |
| Priorities | Kept rules keep their priority when their relative order holds and new rules fit into the gaps. Otherwise every rule is renumbered in steps of 100. An unchanged file writes nothing. | 5.3 |
| "Changed since rendered" | The rendered file carries `base = "<16 hex>"`, a fingerprint of the rule set it was rendered from. Plan and apply refuse when it does not match the stored set. A file with no `base` is applied against the current set. | 6 |
| Plan, prompt, apply | Two transactions. A read-only plan comes first, then the prompt and the editor with no transaction open, then an apply that re-plans and checks the base again. | 6 |
| `classify-rules` record | New column `classifications.rerun_rule_id` (nullable FK to `rules`). `final_account_id` moves, `corrected` stays false, and `proposed_account_id` and `matched_rule_id` are untouched. A CHECK allows at most one of `matched_rule_id` and `rerun_rule_id`. | 7 |
| `classify-rules` scope | Untouched fall-through lines only: final account in a bucket, no matched rule, no rerun rule, not corrected, not split. | 7.2 |
| `add-rule` | Single pattern, appended after the last live rule. It refuses an exact duplicate of a live rule. `--priority` is removed (§16 item 1). | 8 |
| `list-rules` | Columns `id`, `account`, `conditions` (the inline form), in evaluation order. | 8 |
| Slice order | Unchanged: 082 → … → 089. The `note` column moves into 082's migration. The `base` line lands with `show-rules` in 083. The duplicate refusal in `add-rule` lands in 084. | 15 |

**New files**

| File | Contents | Slice |
|---|---|---|
| `kohle/use_cases/conditions.py` | `When`, `AmountRange`, `Direction`, parse, render, `compile_when`, `toml_string` | 082 (grows in 084–086) |
| `kohle/db/migrations/versions/<rev>_rule_condition_trees.py` | `rules.condition`, `rules.note`, drop `pattern`, downgrade | 082 |
| `kohle/db/migrations/versions/<rev>_rerun_rule_on_classifications.py` | `classifications.rerun_rule_id`, CHECK, downgrade | 088 |
| `tests/test_conditions.py`, `tests/test_rule_file.py`, `tests/test_rules_cli.py`, `tests/test_classify_rules.py` | See §17 | 082–088 |

**Changed:** `kohle/domain/models.py`, `kohle/domain/domain_errors.py`,
`kohle/use_cases/rules.py`, `kohle/use_cases/journal.py` (the matcher call
only), `kohle/use_cases/classification.py`,
`kohle/services/rule_services.py`,
`kohle/services/classification_services.py`, `kohle/db/schema.py`
(`HEAD_REVISION`), `kohle/app/cli/cli.py`, `README.md`, `AGENTS.md`, and the
tests named per slice in §15.

**The existing patterns this follows.**

- **Canonical user syntax as stored text.** `sampling_rule_lists.rules` and
  `cap_entries.rule` hold the text the user's command takes, parsed on read
  and rendered on write (CS §14, BG §13 rejected JSON). The condition column
  does the same with the TOML the user edits.
- **A pure grammar module beside the use cases that use it.**
  `recurrence.py` is used by `sampling.py` and `budgeting.py`.
  `conditions.py` is used by `rules.py`, and later perhaps by
  `expected-payments`.
- **Retire, never delete.** `remove_rule_service` is reused as is for every
  retirement.
- **An error that names a row and a field.** `MalformedStatementRow(number,
  field, problem)` is the model for `MalformedRuleFile(position, key,
  problem)`.
- **ORM rows do not cross the session.** As `UnclassifiedLine` does,
  `StoredRule`, `RulePlan` and `RerunMove` are frozen dataclasses.
- **Corrections post a reversing pair, through `post_entry`, dated at the
  original entry.** `classify-rules` shares `reclassify`'s code for this
  (§7.4).

---

## 2. Decision 1: how the condition tree is stored

### 2.1 The columns

```python
class Rule(base, Archivable):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The rule's `when` table as one canonical TOML inline table. Immutable,
    # like account_id: a classification's matched_rule_id must keep meaning
    # what matched.
    condition: Mapped[str] = mapped_column(String, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    account: Mapped["Account"] = relationship("Account")
```

- **`condition`** is exactly what `render_when_inline` produces (§3.4), for
  example `{ iban = "DE89370400440532013000", amount = { min = 400, max = 600 }, direction = "out" }`.
  It is parsed back with `tomllib.loads("when = " + text,
  parse_float=Decimal)` and the same checks as a file (§3.3).
- **`account_id` stays a foreign key** rather than an account name inside
  the text. That keeps referential integrity, and a future account rename
  (qualified paths) changes no rule.
- **`note`** is free text. NULL means no note, and `""` is normalised to
  NULL.
- **`priority` loses its column default.** Every insert computes it (§5.3,
  §8). `DEFAULT_RULE_PRIORITY` is replaced by `RULE_PRIORITY_STEP = 100` in
  `rules.py`.
- **No unique constraint,** for the same reason as today: retired rows stay.
  A partial unique index over live rows was considered and rejected (§14).

### 2.2 Why canonical text and not rows or JSON

- **The spec's own brief, one column per condition,** cannot hold OR or
  NOT.
- **Rows (`rule_conditions` as an adjacency list with `parent_id`, `kind`,
  `value`, `low`, `high`, `position`).**
  - Reading a rule becomes a tree rebuild.
  - Content identity still needs a canonical tree, so rows add a
    representation rather than replace one.
  - The amount bounds would sit in a `Numeric` column, which SQLite stores
    as REAL. The spec says amounts are exact decimals, never floats. Text
    keeps `400.10` exact.
  - The one thing rows buy is SQL over conditions, and compiling rules to
    SQL is a non-goal.
- **JSON.** CS §14 and BG §13 already rejected this for recurrence rules: it
  couples storage to internal names and adds a second serialiser. JSON also
  has no exact decimal, so `json.dumps` of a `Decimal` needs a custom hook,
  which is a third convention.
- **Canonical TOML text** reuses the parser and the checks the file needs.
  It is the string `list-rules` prints, and a stored rule reads as what the
  user wrote. A new condition kind (BG's contract for recurrence kinds)
  needs no migration.
- **Comparisons are structural, never on the text.** The planner parses the
  stored text into a `When` and compares dataclasses (§5.1). If the
  canonical rendering ever changes, stored rows written by an older renderer
  still compare equal. The migration's own quoting (§2.4) therefore only has
  to produce valid TOML that parses back to the pattern.

### 2.3 What is immutable

- **`condition` and `account_id` are never updated.** No service takes them
  as an update argument, so the immutability is structural rather than a
  convention.
- **`update_rule_service(ctx, rule_id, priority, note)`** is the only update
  path. An apply calls it when a kept rule moves or its note changes.
- **`deleted_at` is set only by `remove_rule_service`,** from `remove-rule`
  or from an apply that retires a rule.
- **A retired rule is never revived.** An apply matches file rules against
  live rules only. A file that brings back a retired rule's content creates
  a new rule (§14).

### 2.4 Migration `<rev>_rule_condition_trees.py` (082, revises `b8d4f0a6c235`)

**Upgrade:**

1. `op.add_column('rules', condition String NULL)` and `op.add_column('rules', note String NULL)`.
2. For every row, retired ones included (their text is what keeps a past
   classification interpretable, EC §4.3): `UPDATE rules SET condition = '{ any_field = ' || <quoted pattern> || ' }' WHERE id = :id`.
   This runs in Python with the migration's own `_toml_string`, a copy of
   §3.4's quoting rule. Migrations import no application code. A copy that
   later drifts from the renderer still parses (§2.2).
3. `batch_alter_table('rules')`: `condition` becomes NOT NULL, and `pattern`
   is dropped. Batch mode is needed because SQLite cannot tighten a column in
   place. `_upgrade_to_head` runs with foreign keys off, so recreating
   `rules` under `classifications.matched_rule_id` is safe. The FK text in
   `classifications` keeps naming `rules`.

Ids, priorities, accounts and `created_at`/`deleted_at` are copied
unchanged. `classifications` is not touched. Notes start NULL.

**Downgrade:** `_refuse_if_unrepresentable` parses every `condition` with
`tomllib`. It counts the rows whose `when` is anything but exactly
`{"any_field": str}`, plus the rows with a non-NULL `note`. If any, it
raises the house message ("Refusing to downgrade: N classification rule(s)
use conditions or notes the previous schema cannot hold…"). Otherwise it
adds `pattern`, fills it from `any_field`, and uses batch mode to make it
NOT NULL and drop `condition` and `note`.

`HEAD_REVISION` in `kohle/db/schema.py` moves to this revision. The test
pinning it fails until it does.

### 2.5 Duplicate rules already stored

Today two live rules can carry the same pattern and account; the model
comment calls them dead weight. The migration converts them faithfully, so
`show-rules` renders both, and the file check rejects two identical rules.
On a ledger holding such a pair, the first `show-rules | apply-rules --yes`
is rejected with "rule 7: has the same account and conditions as rule 3".
The user deletes one line, and the apply then retires the later duplicate.
That rule could never fire, because the identical earlier rule always wins.
This is the one case where the round-trip guarantee does not hold, and only
until the user removes the duplicate. §16 item 2 asks the user to accept it.
From 084, `add-rule` refuses to create a new duplicate (§8), so none can
appear after the migration.

---

## 3. The condition language (`kohle/use_cases/conditions.py`)

### 3.1 Types

```python
PATTERN_FLAGS = re.IGNORECASE          # moved here from rules.py, comment kept

class Direction(Enum):
    incoming = "in"
    outgoing = "out"

@dataclass(frozen=True, slots=True)
class AmountRange:
    low: Decimal | None                # at least one end set; 0 <= low <= high
    high: Decimal | None

@dataclass(frozen=True, slots=True)
class When:
    """One TOML condition table: every key present must hold.

    One field per key rather than a node hierarchy, because a TOML table can
    hold each key once. Equality is then content identity, independent of key
    order in the file."""
    description: str | None = None
    counterparty: str | None = None
    iban: str | None = None            # normalised: no whitespace, upper case
    amount: AmountRange | None = None
    direction: Direction | None = None
    any_field: str | None = None
    any_of: tuple["When", ...] = ()    # the `any` key; () means absent
    not_: "When | None" = None         # the `not` key
```

- **Invariant:** a `When` holds at least one condition, and every nested
  one does too. The parser guarantees it.
- **The canonical key order** is `KEYS = ("description", "counterparty",
  "iban", "amount", "direction", "any_field", "any", "not")`. That is the
  spec's Goals order with the combinators last. It drives parsing, rendering
  and evaluation.
- **Slices add fields.** In 082 `When` has only `any_field`. 084 adds
  `description`, `counterparty` and `iban`. 085 adds `amount` and
  `direction`. 086 adds `any_of` and `not_`. Each slice adds the field, its
  parse branch, its render branch and its compile branch together, so no
  slice accepts a key it cannot render or evaluate.

### 3.2 Semantics

The inputs are the line's description (`str`), its `Counterparty` (name and
IBAN, each `str | None`, as stored), and its signed amount (`Decimal`;
negative means money left the imported account).

| Key | Holds when |
|---|---|
| `description` | `pattern.search(description)` |
| `counterparty` | name is not None and `pattern.search(name)` |
| `iban` | iban is not None and `normalise_iban(iban) == value` |
| `amount` | `low <= abs(amount) <= high`, a missing end being open |
| `direction` | `in`: amount > 0; `out`: amount < 0 |
| `any_field` | `pattern.search(f)` for some non-None f of description, name, iban (today's semantics, exactly) |
| `any` | some item holds |
| `not` | its table does not hold |

Each table is the AND of its keys.

- **Patterns are case-insensitive** (`PATTERN_FLAGS`, unchanged).
- **`any_field` matches the stored IBAN raw,** not normalised, so migrated
  rules behave exactly as before. That includes anchored `^DE89…$`
  patterns.
- **`normalise_iban(s) = "".join(s.split()).upper()`.** It is applied to
  the rule's value when parsed and to the line's IBAN when evaluated.
- **A zero amount** satisfies neither direction (§16 item 5), and `abs(0)
  = 0` is tested against the range as usual.
- **A missing counterparty** makes `counterparty` and `iban` false, so
  `not` over them is true. That is the spec's rule, and it falls out of the
  table above with no special case.

### 3.3 Parsing and checks

```python
def parse_when(value: object, key: str = "when") -> Result[When, MalformedRuleFile]
def parse_stored_when(text: str) -> Result[When, MalformedRuleFile]
```

`parse_when` walks what `tomllib` returned. Every error carries the dotted
key path (`when.any[2].not.iban`) and leaves `position` unset; the rule-file
parser attaches the position (§4.2). It rejects:

- a value that is not a table, or a table with no keys. That covers a rule
  with no conditions, an empty `not`, and an empty item inside `any`;
- an unknown key;
- `any` that is not an array of tables, or an empty `any`;
- a pattern that is not a string, is empty after `strip()`, or does not
  compile with `PATTERN_FLAGS`. The `re.error` message is included;
- `iban` that is not a string, or that is empty or not letters and digits
  after normalisation. This catches a regex typed into `iban` by habit, and
  the message points at `any_field` or `counterparty` for patterns;
- `amount` that is not a table, has a key other than `min`/`max`, or has
  neither key;
- a bound that is a `bool` (Python's `bool` is an `int`, so this check comes
  first), is not an `int` or `Decimal`, is not finite (TOML `nan`/`inf`
  arrive as `Decimal`), or is negative ("the range is on the absolute
  amount; use direction for the sign");
- `min` above `max`;
- `direction` other than the strings `"in"` and `"out"`.

**Numbers stay exact.** The file is read with `tomllib.loads(text,
parse_float=Decimal)`, and an `int` bound becomes `Decimal(int)`. This is
how "amounts are compared as exact decimals, never as floats" holds. Without
`parse_float`, `min = 400.1` arrives as a float.

**Patterns are taken verbatim,** not stripped as `add-rule` strips its shell
argument: a TOML string is quoted, so leading spaces are deliberate. Notes
are verbatim, except that an empty note means no note.

`parse_stored_when` wraps the text in `when = …`, parses it, and calls
`parse_when`. A stored row that fails can only come from a hand edit; the
caller reports it as `RuleError("stored rule 7: …")` (§9).

### 3.4 Rendering: Decision 2, our own canonical renderer

```python
def render_when_inline(when: When) -> str      # storage, list-rules, nested tables
def render_when_lines(when: When) -> list[str] # the body under [rule.when]
def toml_string(s: str) -> str
def toml_decimal(d: Decimal) -> str
```

- **Keys** are written in `KEYS` order. A `None` field and an empty `any_of`
  are omitted. `amount` writes `min` before `max` and omits an open end.
- **Strings** follow one deterministic rule, verified against `tomllib` on
  quotes, backslashes, tabs, newlines, DEL, non-ASCII and NUL:
  1. If the string has no `"`, no `\` and no control character other than
     tab, write a basic string: `"REWE|ALDI"`.
  2. Otherwise, if it has no `'` and no control character other than tab,
     write a literal string: `'\d{4} MIETE'`. Regexes keep single
     backslashes, which is the main readability win over any library
     writer.
  3. Otherwise write a basic string with `\\`, `\"`, `\b`, `\t`, `\n`, `\f`,
     `\r`, and `\uXXXX` for the other control characters and U+007F.
- **Decimals:** `format((d + 0).normalize(), "f")`. So `400`, `400.0` and
  `4E+2` all render `400`; `400.50` renders `400.5`; `-0` renders `0`. The
  output is always a valid TOML integer or float literal, and never an
  exponent.
- **Inline form:** `{ k = v, k = v }`. A nested `any` is `any = [{ … }, { … }]`
  on the one line, since TOML 1.0 inline tables cannot span lines.
- **Table body form,** as used under `[rule.when]`: one `key = value` line
  per key. `any` is written one alternative per line:

  ```toml
  any = [
    { description = "rewe" },
    { counterparty = "edeka", not = { description = "pfand" } },
  ]
  ```

  `not` is one line: `not = { … }`.
- **The order of `any` alternatives is the user's.** It is part of content,
  so swapping two alternatives retires and re-adds the rule (§14).

The round-trip property is `parse_when(tomllib(render(w))) == w` for every
valid `w`. It holds for both forms, and §17 tests it as a table of cases.

### 3.5 Compiling and evaluating

```python
Predicate = Callable[[str, Counterparty, Decimal], bool]

def compile_when(when: When) -> Predicate
```

- **Closures.** Each present key becomes a closure, with its pattern
  compiled once. The AND is `all(test(d, c, a) for test in tests)`, `any` is
  `any(...)` over the compiled items, and `not` is negation.
- **Short-circuit** comes from `all`/`any` over generators, in `KEYS` order.
  A child's result is computed before its parent's, as the spec requires.
- **Pure.** No session, no I/O, and no state beyond the compiled patterns
  captured per call.
- **Why closures:** the alternative is a second tree type that mirrors
  `When` with `re.Pattern` in place of `str`. That is more code, and nothing
  needs to inspect it.

---

## 4. The rule file

### 4.1 Layout

```toml
# kohle classification rules, in priority order: the first rule that matches
# a line wins. Keys under [rule.when] must all hold; any = [...] needs one of
# its tables to hold; not = {...} must not hold.
# Leave `base` as it is: apply-rules uses it to refuse if the stored rules
# changed after this file was rendered.
base = "4f0c2d9e8a1b7c35"

[[rule]]
account = "Household"
note = "monthly share to partner"
[rule.when]
iban = "DE89370400440532013000"
amount = { min = 400, max = 600 }
direction = "out"

[[rule]]
account = "Groceries"
[rule.when]
any = [
  { description = "rewe" },
  { counterparty = "edeka", not = { description = "pfand" } },
]
```

- **Allowed keys.** Top level: `base` (optional string) and `rule` (an array
  of tables). Per rule: `account` (required, non-empty string), `note`
  (optional string), `when` (required table).
- **Accepted forms.** Any TOML that produces this data is accepted, such as
  `when = { … }` inline or `[[rule.when.any]]` sections. The checks run on
  the parsed data, and rendering always produces the canonical layout above.
- **Separators.** There is one blank line between rules, and the file ends
  with a newline.
- **Ids never appear.**

### 4.2 `parse_rule_file`

```python
@dataclass(frozen=True, slots=True)
class FileRule:
    position: int          # 1-based index among [[rule]] entries
    account: str
    note: str | None
    when: When

@dataclass(frozen=True, slots=True)
class RuleFile:
    base: str | None
    rules: tuple[FileRule, ...]

def parse_rule_file(text: str) -> Result[RuleFile, MalformedRuleFile]
```

The parser stops at the first error. Each error names the rule's position
and the key at fault, except syntax errors and top-level key errors, which
have no rule.

1. `tomllib.loads(text, parse_float=Decimal)`. A `TOMLDecodeError` becomes
   `MalformedRuleFile(None, None, "not valid TOML: <message>")`. Python
   3.12's message already ends in `(at line L, column C)`.
2. An unknown top-level key, `base` that is not a string, or `rule` that is
   not an array of tables.
3. Per rule: an unknown key, a missing or empty `account`, a non-string
   `note`, then `parse_when(rule["when"], "when").map_err(lambda e:
   e.at(position))`.
4. **Duplicates.** Two rules whose `(when, account)` are equal give
   `MalformedRuleFile(j, None, "has the same account and conditions as rule
   i")`. The account name stands in for the account id here, because names
   are globally unique and lookup is exact.

Account existence and the leaf check need the ledger, so they happen in the
plan (§5). They still produce `MalformedRuleFile(position, "account", …)`,
so `edit-rules` treats them like any other file error.

### 4.3 `render_rule_file` and the base

```python
def rule_set_base(rules: Sequence[StoredRule]) -> str      # sha256 of the body, first 16 hex
def render_rule_file(rules: Sequence[StoredRule]) -> str   # header + base line + body
```

- **The body** is the `[[rule]]` entries in evaluation order. The header
  comment is a constant.
- **The base** is a function of the body alone. The same rule set therefore
  always renders the same text, base included, and an empty set has a fixed
  base.
- **What the base covers:** order, accounts (by name), notes and
  conditions. Ids and priority values do not appear, so a change invisible
  in the file is not a change in the base.

---

## 5. Identity, the plan, and priorities

### 5.1 Stored rules and matching by content

```python
@dataclass(frozen=True, slots=True)
class StoredRule:
    rule_id: int
    priority: int
    account_id: int
    account_name: str
    when: When
    note: str | None

def stored_rules(ctx) -> Result[list[StoredRule], RuleError]
```

- **`stored_rules`** calls `list_rules_service`, keeping its `(priority,
  id)` order contract and the joinedload of the account, and parses each
  `condition`. The import, `list-rules`, `show-rules`, the plan and
  `classify-rules` all read rules through it.
- **Matching.** For each file rule in file order, take the first unmatched
  live rule, in evaluation order, with the same `(when, account_id)`. That
  pair is *kept* and keeps its id. File rules with no match are *added*.
  Live rules left unmatched are *retired*. "First unmatched" only matters
  for §2.5's legacy duplicates.

### 5.2 The plan

```python
@dataclass(frozen=True, slots=True)
class PlannedRule:
    rule: FileRule
    kept: StoredRule | None   # None: added
    priority: int             # priority after apply

@dataclass(frozen=True, slots=True)
class RulePlan:
    base: str                          # fingerprint of the stored set planned against
    rules: tuple[PlannedRule, ...]     # file order
    retired: tuple[StoredRule, ...]    # evaluation order
    reordered: frozenset[int]          # ids of kept rules that moved

    # properties: added, renoted, unchanged (count), updates, is_empty

def plan_rule_changes(
    stored: Sequence[StoredRule], file: RuleFile, account_ids: Mapping[str, int], base: str
) -> RulePlan
```

The planner is pure. The summary categories are these:

- **added** and **retired**, as in §5.1;
- **reordered**: kept rules outside one longest increasing subsequence of
  their old evaluation indices, taken in file order. Moving one rule from
  the top to the bottom reports one reordered rule, not every rule. This is
  the classic patience algorithm with predecessor links, about 15 lines;
- **note changed**: kept rules whose note differs. This category is not in
  the spec's list (§16 item 6). Without it a note-only edit would be
  confirmed against a summary that shows nothing;
- **unchanged**: kept rules that are neither reordered nor renoted.

`is_empty` is true when nothing is added or retired and no kept rule's
priority or note changes. An empty plan is never applied, so it leaves no
`OperationGroup`.

### 5.3 Priority assignment

The constraint is that evaluation order after the apply must equal file
order, because of `ORDER BY priority, id`. The spec adds two requirements:
an unchanged file writes nothing, and a moved rule changes only its
priority. Rewriting every priority would satisfy the first constraint but
leave every apply with N updates in the audit trail. So the planner keeps
priorities where it can:

```
STEP = RULE_PRIORITY_STEP (100)
If the kept rules, taken in file order, are strictly increasing in (priority, id):
    every kept rule keeps its priority
    each maximal run of added rules gets one priority p:
        no kept rule at all        -> the i-th added rule gets STEP * (i + 1)
        only a kept rule after it  -> p = next.priority - STEP
        only a kept rule before it -> p = prev.priority + STEP
        kept rules on both sides   -> p = (prev.priority + next.priority) // 2,
                                      valid only if next.priority > prev.priority
    if any run is not valid: fall through to renumbering
Otherwise renumber: the i-th file rule gets STEP * (i + 1)
```

- **The id assumption.** Within a run, rules share `p` and are ordered by
  id. New ids are larger than every existing id: SQLite's rowid is
  `max + 1`, and rules are never hard-deleted. The apply inserts added
  rules in file order (§5.4), which makes this hold.
- **Ties after `p == prev.priority`** are correct for the same reason: the
  new id is larger than the previous rule's.
- **Negative priorities** can appear at the front, and are fine.
- **When renumbering happens.** Renumbering writes `update_rule_service`
  only where a kept rule's priority actually changes. It happens when the
  user reorders rules, or inserts between two rules that tie on priority.
  Ties are common on ledgers built with the old default of 100, so the
  first such insert renumbers the whole set once. The summary still counts
  those rules as unchanged, because their order did not change; only an
  internal number did.

### 5.4 Apply order and the audit trail

There is one transaction and one `OperationGroup`. Within it the apply:

1. retires through `remove_rule_service` (`crud_delete`, "retired" being
   what happened, as for `remove-rule`);
2. updates priority and note through `update_rule_service` (`crud_update`),
   one `Operation` per changed rule;
3. adds through `add_rule_service(ctx, render_when_inline(when), account_id,
   priority, note)` (`crud_create`), in file order.

Any failure rolls the whole transaction back.

---

## 6. Concurrency: the base, and plan then apply

- **The two use cases.** `PlanRuleFile.execute(text)` is read-only.
  `ApplyRuleFile.execute(text, base)` writes. Both parse the text before
  opening the transaction, as `SetSamplingRules` does. Inside the
  transaction both load `stored_rules`, compute the current base, resolve
  accounts and plan.
- **The plan's checks.** If the file has a `base` and it differs from the
  current base, the plan returns `RulesChanged`. A file without `base`
  (hand-written, or empty) is planned against the current set. That is the
  only reading under which "an empty file retires all rules" can work (§16
  item 3). The returned plan carries the base it saw.
- **The apply's check.** The caller passes the plan's base. If the stored
  set's base differs at apply time, the result is `RulesChanged` with
  nothing written. Otherwise the apply re-plans, which also re-runs the
  account checks in case an account gained a child after the plan, and
  writes.
- **Nothing is held open.** No transaction is open while the editor or the
  prompt waits. In WAL mode, an open read transaction that later wants to
  write fails with `SQLITE_BUSY_SNAPSHOT` once another writer commits. In
  rollback-journal mode it blocks writers. Either way, a person at a prompt
  must not hold one.
- **The base comes from the file because `apply-rules` takes an arbitrary
  file.** The process that rendered it is gone, so the file is the only
  place the "rendered from" state can travel. For `edit-rules` the base
  also comes from the file it rendered; a user who deletes the line opts
  out, and that is the same rule for both commands.
- **`classify-rules` uses the same shape** (§7.5). It previews in one
  transaction and applies in a second, which re-plans and refuses with
  `ClassifyPlanChanged` if the moves differ.

---

## 7. `classify-rules`: Decision 3, how the move is recorded

### 7.1 The record

```python
class Classification(base, Archivable):
    ...
    matched_rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id"), nullable=True)
    # The rule a classify-rules run moved this line with, set only on a line
    # that fell through at import. Not folded into matched_rule_id:
    # proposed_account_id must stay where the import entry put the line,
    # because reclassify and split-line find the original line through it.
    rerun_rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id"), nullable=True)
    ...
    matched_rule: Mapped["Rule | None"] = relationship("Rule", foreign_keys=[matched_rule_id])

    __table_args__ = (
        UniqueConstraint("journal_entry_id", name="uq_classification_journal_entry"),
        # COALESCE(matched_rule_id, rerun_rule_id) is "the rule responsible",
        # which is only well defined if at most one is set.
        CheckConstraint("matched_rule_id IS NULL OR rerun_rule_id IS NULL",
                        name="ck_classification_one_rule"),
    )
```

The rows look like this in each state:

| State | proposed | matched_rule | final | corrected | rerun_rule |
|---|---|---|---|---|---|
| Import, rule R matched | X | R | X | false | NULL |
| Import, fell through | bucket | NULL | bucket | false | NULL |
| Then `classify-rules` moved it by R | bucket | NULL | X | false | R |
| Then a human corrected it | unchanged | unchanged | Y | **true** | unchanged |

- **Distinguishable from a human correction:** `corrected` is false and
  `rerun_rule_id` is set.
- **It records the rule that matched.** Rules are immutable, so
  `rerun_rule_id → rule.account_id` recovers where the rule sent the line,
  even after a human later corrects it.
- **`proposed_account_id` stays on the bucket.** `Reclassify` and
  `SplitImportedEntry` locate the original counterpart line by
  `proposed_account_id`. Overwriting it with X would make `next(...)` find
  no line, and a later correction or split of the moved line would fail.
- **The invariant `matched_rule.account_id == proposed_account_id` still
  holds,** so readers of the existing column are undisturbed.

`set_classification_outcome_service` keeps meaning a human correction. A new
`set_rerun_outcome_service(ctx, classification_id, final_account_id,
rule_id)` (`crud_update`) sets `final_account_id` and `rerun_rule_id` and
leaves `corrected` false. The `Classification` docstring's "they diverge
only when a human corrects the line" becomes "…or when `classify-rules`
moves it, which `rerun_rule_id` records".

### 7.2 Which lines it covers

```python
def rerun_candidates_service(ctx, bucket_account_ids) -> Result[list[Classification], ClassificationError]
```

The service selects:

```
final_account_id IN buckets
AND matched_rule_id IS NULL      -- a rule classified it at import (even into a bucket)
AND rerun_rule_id IS NULL        -- a previous classify-rules run classified it
AND NOT corrected                -- a human touched it, even back into a bucket
AND NOT EXISTS (SELECT 1 FROM splits WHERE splits.journal_entry_id = classifications.journal_entry_id)
```

It eager-loads the entry and its lines (`selectinload`) and the final
account (`joinedload`), and orders by entry date, then entry id. This
mirrors `unclassified_classifications_service`.

- **The result is exactly the untouched fall-throughs.** The spec says it
  "never touches a line a rule already classified or a human reclassified".
- **Split lines are left out,** because `reclassify` refuses them
  (`EntryAlreadySplit`): the bucket no longer holds the full amount (§16
  item 7).
- **Buckets are resolved strictly,** as in `ListUnclassified`. With no
  buckets yet there is nothing to do, and nothing is created.

### 7.3 What the rules see

The same inputs the import gave them:

- `entry.description`;
- `Counterparty(entry.counterparty_name, entry.counterparty_iban)`, which
  were stored after `_optional_str`;
- the signed amount, derived from the bucket line (the line on
  `proposed_account_id`): `-value if line.is_debit else value`. At import
  the counterpart is debited exactly when `amount < 0`.

One helper, `_rule_amount(classification)`, owns that derivation. The stored
quantity is `Numeric(20, 8)`, so any amount with up to 8 decimals compares
exactly as it did at import.

### 7.4 The correcting entry

`Reclassify`'s posting moves into `_post_correction(ctx, classification,
to_account_id, description) -> Result[JournalEntry, JournalError]` in
`classification.py`.

- It finds the original line by `proposed_account_id`, reverses it out of
  `final_account_id`, and posts onto the target. The entry is dated at the
  original date, gets a uuid reference, and goes through `post_entry`.
- `Reclassify` calls it with `f"Reclassify: {entry.description}"` and keeps
  its split guard and `set_classification_outcome_service` call.
- `classify-rules` calls it with `f"Classify: {entry.description}"`, so
  `entries-in-period` shows why each correcting entry exists.
- `post_entry` itself does not change. The spec's "Places this touches"
  names it, but the shared seam is the correction path above it.

### 7.5 Plan and apply

```python
@dataclass(frozen=True, slots=True)
class RerunMove:
    entry_id: int
    entry_date: date
    description: str
    amount: Decimal          # signed, as the rules saw it
    bucket_name: str
    rule_id: int
    account_id: int
    account_name: str
```

**`_plan_moves(ctx)`** runs inside a transaction:

1. resolve the buckets;
2. load the candidates;
3. call `stored_rules` and `compile_rules`;
4. match each candidate, keeping it only when `matched.account_id !=
   final_account_id`. A rule aimed at the bucket the line is already in
   moves nothing;
5. check each distinct target with `account_has_children_service`, and
   return `PostingToNonLeafAccount` before any preview. The preview then
   never promises a move the apply would refuse, and the failure matches
   the import's.

**`PlanClassifyRules.execute()`** is read-only and returns
`list[RerunMove]`.

**`ApplyClassifyRules.execute(expected)`** writes:

- It re-plans and compares `(entry_id, rule_id, account_id)` tuples with
  `expected`. On any difference it returns `ClassifyPlanChanged` with
  nothing written. That catches an import, a reclassify or a rule change
  between the preview and the answer.
- Otherwise, for each move, it calls `_post_correction` and then
  `set_rerun_outcome_service`.
- Everything happens in one transaction and one `OperationGroup`.

**Rule changes never reclassify.** `AddRule`, `ApplyRuleFile` and
`RemoveRule` never touch `journal_entries` or `classifications`.

### 7.6 Migration `<rev>_rerun_rule_on_classifications.py` (088)

- **Upgrade.** `batch_alter_table('classifications')` adds `rerun_rule_id`
  (Integer NULL), creates the FK `fk_classification_rerun_rule` to
  `rules.id`, and creates the CHECK `ck_classification_one_rule`. Batch
  mode is required: SQLite cannot add a foreign key or a CHECK to an
  existing table. No table references `classifications`.
- **Downgrade.** `_refuse_if_unrepresentable` counts the rows with
  `rerun_rule_id IS NOT NULL`. These are labelled data the ledger cannot
  rebuild, so if any exist the downgrade refuses. Otherwise batch mode
  drops the column and the constraints.
- **`HEAD_REVISION`** moves to this revision.

---

## 8. Existing commands and the import

- **`add-rule PATTERN ACCOUNT`** (082):
  - The pattern is stripped, empty and malformed patterns are refused as
    today (`EmptyRulePattern`, `InvalidRulePattern`), and a non-leaf target
    is refused as today.
  - It creates `condition = render_when_inline(When(any_field=text))`.
  - The priority is the highest live priority plus `RULE_PRIORITY_STEP`, or
    `RULE_PRIORITY_STEP` when there is no live rule. That is "the end of
    the order".
  - `--priority` is removed (§16 item 1).
  - From 084 it refuses `DuplicateRule(rule_id)` when a live rule has the
    same `When` and account.
  - The output is `Added rule 12: { any_field = "REWE|ALDI" } -> Groceries`.
- **`list-rules`** (082): `ListRules` returns `list[StoredRule]`. The
  tabulate columns are `id`, `account` and `conditions`
  (`render_when_inline`), in evaluation order. An empty set still prints
  `No rules`. Notes and priorities are not shown, because the spec names
  the columns.
- **`remove-rule`:** unchanged.
- **The import** (`ImportStatement.execute`) calls `stored_rules(ctx)` and
  `compile_rules(...)` once per statement, as today. Its call becomes
  `match_rule(compiled, row.description, counterparty, row.amount)`; the
  amount argument arrives in 085. Everything else in the loop is unchanged.
- **The matcher:**

  ```python
  @dataclass(frozen=True, slots=True)
  class CompiledRule:
      rule_id: int
      account_id: int
      holds: Predicate

  def compile_rules(rules: Iterable[StoredRule]) -> list[CompiledRule]   # order-preserving, never sorts
  def match_rule(compiled, description: str, counterparty: Counterparty, amount: Decimal) -> CompiledRule | None
  ```

  - `compile_rules` returns a plain list, as today. `stored_rules` has
    already validated every pattern, so compilation cannot fail.
  - `match_rule` stays pure and first-match-wins.

---

## 9. Use cases

| Use case | Module | Transaction | Returns | Slice |
|---|---|---|---|---|
| `AddRule.execute(pattern, account_name)` | `rules.py` | write | `Rule` | 082, 084 |
| `ListRules.execute()` | `rules.py` | read | `list[StoredRule]` | 082 |
| `RemoveRule.execute(rule_id)` | `rules.py` | write | unchanged | — |
| `ShowRules.execute()` | `rules.py` | read | `str` (the rendered file) | 083 |
| `PlanRuleFile.execute(text)` | `rules.py` | read | `RulePlan` | 084 |
| `ApplyRuleFile.execute(text, base)` | `rules.py` | write | `RulePlan` | 084 |
| `PlanClassifyRules.execute()` | `classification.py` | read | `list[RerunMove]` | 088 |
| `ApplyClassifyRules.execute(expected)` | `classification.py` | write | `list[RerunMove]` | 088 |

The plan and apply pairs share a private `_plan(ctx, rule_file)` and
`_plan_moves(ctx)` respectively. Inside `_plan`:

- each distinct account name is resolved with `get_account_by_name_service`
  and `account_has_children_service`;
- `AccountNotFoundError` becomes `MalformedRuleFile(first position naming
  it, "account", "no account named 'X'")`;
- a parent becomes `MalformedRuleFile(position, "account", "'X' has
  sub-accounts; a rule must send lines to a leaf account")`;
- any other `AccountError` (an infrastructure failure) passes through
  unchanged.

**Imports.** `classification.py` gains imports from `rules.py`. `rules.py`
imports neither `journal.py` nor `classification.py`, and `journal.py` still
never imports `classification.py`, so no import cycle appears.

---

## 10. CLI (`kohle/app/cli/cli.py`)

Every new command registers `writes=` explicitly, and that flag is the whole
reader-device change. `_KohleCommand.invoke` refuses a `writes=True` command
on a reader before its body runs, so before any file is read or any editor
opened. `tests/test_reader.py`'s `_WRITE_ARGV` and `_read_argv` gain the
entries.

| Command | `writes` | Flow |
|---|---|---|
| `show-rules` | False | `click.echo(ShowRules(...).execute(), nl=False)` |
| `apply-rules FILE [--yes]` | True | Read FILE (`click.File("rb")`, so `-` reads stdin; decode UTF-8 and turn `UnicodeDecodeError` into `ClickException`). Then `PlanRuleFile`. If the plan is empty, print `No changes` and exit 0. Otherwise print the summary, then `click.confirm("Apply these changes?", abort=True)` unless `--yes`, then `ApplyRuleFile(text, plan.base)` and print `Applied: …`. |
| `edit-rules` | True | §10.1 |
| `classify-rules [--yes]` | True | `PlanClassifyRules`. If empty, print `No unclassified line matches a rule` and exit 0. Otherwise print the preview table (`entry_id`, `date`, `description`, `amount` (signed), `from` (bucket), `to`, `rule` (id)) and confirm (`Move N line(s)?`) unless `--yes`. Then `ApplyClassifyRules(moves)` and print `Moved N line(s)`. |

- **Summary format.** First a count line: `1 added, 1 retired, 1
  reordered, 0 note changed, 12 unchanged`. Then one line per added rule
  (`rule 3 (new) -> Household { … }`), per retired rule (`id 7 -> Household
  { … }`), per reordered rule (`id 4 -> Rent, now rule 1`) and per note
  change. Tests assert the count line. The detail lines are the
  implementer's to lay out.
- **Declining a prompt** uses click's `abort=True`: `Aborted!`, exit 1,
  nothing written. With `-` as FILE and no `--yes`, the prompt reads the
  exhausted stdin and aborts the same way, so piping needs `--yes`.
- **Errors** become `ClickException` (exit 1) through `str(err)`, as
  everywhere.

### 10.1 `edit-rules`

1. Resolve the editor: `os.environ.get("VISUAL") or
   os.environ.get("EDITOR")`. If neither is set, fail with `no editor: set
   $VISUAL or $EDITOR, or use show-rules and apply-rules`. Pass it
   explicitly as `click.edit(..., editor=editor)`. Without that, click falls
   back to `sensible-editor`, `vim`, `nano` or `vi` (checked in the pinned
   click 8.3), and the spec says to fail instead.
2. Get `text = ShowRules(...).execute()`.
3. Loop:
   - `edited = click.edit(text, editor=editor, extension=".toml",
     require_save=True)`. `None` means the user quit without saving: print
     `No changes; nothing applied` and return.
   - `body = _strip_banner(edited)`, then `PlanRuleFile(...).execute(body)`.
   - On `MalformedRuleFile`: `text = _with_banner(body, err)` and loop
     again (the editor reopens).
   - On `RulesChanged`: write `body` to `tempfile.mkstemp(prefix="kohle-rules-",
     suffix=".toml")`, then fail with the error plus `your edits are saved
     in <path>` (§16 item 8).
   - On any other error, fail.
4. An empty plan prints `No changes`. Otherwise print the summary, then
   `click.confirm(..., abort=True)`, then `ApplyRuleFile(body, plan.base)`,
   with `RulesChanged` handled as in step 3.

**The error banner** is exactly two comment lines with a fixed marker:

```
# !! kohle: not applied. Fix the problem below and save, or quit without saving to abort.
# !! rule 3, when.amount: min 600 is above max 400
```

- **Line numbers must match.** A TOML syntax error's line numbers must
  match the reopened buffer. So the parse in step 3 runs on
  `"#\n#\n" + body`, a placeholder of the banner's height, while the user
  sees `banner + body`.
- **The message stays on one line.** `tomllib`'s messages and the design's
  are single-line; newlines are replaced defensively by the banner builder,
  since it controls the height.
- **Where it lives.** The banner is presentation and lives in the CLI. The
  use cases see only `body`.

**Testing.** Tests monkeypatch `click.edit` (§17).

---

## 11. Errors (`kohle/domain/domain_errors.py`)

```python
class MalformedRuleFile(RuleError):
    """One problem in a rule file, named by rule position and key, as
    MalformedStatementRow names a row and a field."""
    def __init__(self, position: int | None, key: str | None, problem: str) -> None: ...
    def at(self, position: int) -> "MalformedRuleFile": ...
    # "rule 3, when.amount: min 600 is above max 400" / "rule 3: has the same …" /
    # "base: must be a string" / "not valid TOML: … (at line 5, column 24)"

class RulesChanged(RuleError):           # base, current
    # "the rules changed after this file was rendered; run show-rules or
    #  edit-rules again, or delete the base line to apply it over the current rules"

class DuplicateRule(RuleError):          # rule_id
    # "rule 7 already sends these lines to that account"

class ClassifyPlanChanged(ClassificationError):
    # "the ledger changed since the preview; run classify-rules again"

ApplyRulesError = RuleError | AccountError
ClassifyRulesError = AccountError | JournalError | ClassificationError | RuleError
```

- **Stored conditions that fail to parse** surface as `RuleError(f"stored
  rule {id}: {problem}")` from `stored_rules`. That only happens after a
  hand edit, and the message names the row.
- **Kept as they are:** `EmptyRulePattern` and `InvalidRulePattern` stay for
  `add-rule`. `AddRuleError` is unchanged; `DuplicateRule` is a
  `RuleError`.

---

## 12. README and AGENTS.md

- **Per slice.** Each slice removes the README statements its own change
  makes false (BG §14 item 4): 082 removes the `--priority` example, the
  "lowest priority first" paragraph and the `pattern` column. Each new
  command gets a stub where the slice adds it.
- **089** writes the full section:
  - the conditions and their semantics (§3.2);
  - the file layout, including `any`/`not` and the one-line limit on OR
    alternatives;
  - `base`;
  - content-based identity, and what keeps an id;
  - the four new commands, and what `list-rules` shows;
  - that command names are flat and may change under `cli-command-naming`.
- **`AGENTS.md`** (089) gains a sentence after the layering paragraph.
  Rules store their condition as canonical TOML text beside an account
  foreign key. The condition and the account are immutable, and a change
  retires the rule and adds a new one. `match_rule` is pure and
  session-free. A `classify-rules` move is recorded in
  `classifications.rerun_rule_id`, never as a correction.
- **No document may still say a rule is a single regular expression.**

---

## 13. The decision categories

### State and data lifecycle

- **Units of work.** `apply-rules`, `edit-rules` and `classify-rules` each
  apply inside one `UnitOfWork`, which is one SQLite transaction and one
  `OperationGroup`.
  - Retirements, updates and creates commit together, or none do. The same
    holds for every correcting entry with its classification update.
  - The plan, the prompt and the editor happen before that transaction
    opens. A failed check, a declined prompt or an aborted editor therefore
    reaches no write at all.
  - A crash part-way leaves an uncommitted transaction, which SQLite rolls
    back.
- **No write, no trace.** An empty plan is never applied. The read-only
  `Plan*` and `ShowRules` use `crud_retrieve`, so they leave no group.
- **Rules are append-and-retire.** `condition` and `account_id` never
  change after insert. Priority and note are updated in place.
  `remove-rule` and the apply retire rules and never delete them. Every
  `matched_rule_id` and `rerun_rule_id` therefore keeps pointing at the
  condition that actually matched.
- **Classifications are never deleted.**
  - Import creates the row.
  - `reclassify` updates `final_account_id` and `corrected`.
  - `classify-rules` updates `final_account_id` and `rerun_rule_id`.
  - `proposed_account_id` and `matched_rule_id` are never rewritten.
- **Reversible, partly.**
  - A rule set can be restored by applying an older rendered file with its
    `base` line removed. Rules that come back get new ids, because retired
    rules are not revived.
  - A `classify-rules` move can be undone by `reclassify`, which records a
    human correction. There is no undo command (`undo-delete-edit` in the
    inbox).
- **Auditable.** `list-operations` shows `rules` create, update and delete,
  `journal_entries` create, and `classifications` update.
- **Replayable.** `show-rules` output is the complete rule state. Applying
  it again is a no-op.
- **Migrations.** Both are all-or-nothing under `migrate`'s staging copy
  (AI §5.5), and both downgrades refuse rather than drop data.

### Error propagation

- **`conditions.py`** returns `MalformedRuleFile` values with a key path and
  no position. It knows nothing of rules, accounts or storage.
- **`parse_rule_file`** attaches positions and adds the file-level and
  duplicate checks.
- **Services** wrap infrastructure failures as `RuleError(str)` or
  `ClassificationError(str)`, unchanged, so nothing above them sees
  SQLAlchemy.
- **The use cases are where representation changes.**
  - Account lookups inside `_plan` turn `AccountNotFoundError` and the leaf
    check into positioned `MalformedRuleFile`s, so every file problem has
    one type the editor loop can branch on.
  - `RulesChanged` and `ClassifyPlanChanged` are their own types, because
    they are not fixable in the file.
  - `PostingToNonLeafAccount` from `_plan_moves` passes through unchanged,
    as for the import.
- **The CLI** branches only in `edit-rules` (malformed: reopen; changed:
  save and fail). Everywhere else it is `str(err)` and exit 1.
- **Corrupt stored text** is a `RuleError` naming the rule. It makes
  imports, `list-rules`, `show-rules` and plans fail loudly. It is never
  silently skipped, since skipping would quietly disable a rule.

### Concurrency and ownership

- **Each `kohle-cli` process is single-threaded** and holds no shared
  mutable state. The compiled closures are local to one import or one plan.
  `re`'s internal cache is the only process-global state touched, and it is
  thread-safe.
- **Processes are serialised by SQLite's locking** and the 30 s busy
  timeout (DT §5).
- **No transaction stays open across a human.** Optimistic checks guard the
  gap: the base fingerprint for rules, and move equality for
  `classify-rules`. A concurrent `add-rule`, `remove-rule`, `apply-rules`,
  import or `reclassify` between preview and apply causes a refusal, never
  a silent overwrite.
- **Two `apply-rules` racing:** both plans see base B, and the first apply
  commits. The second's apply transaction sees a new base and refuses.
- **A reader device** refuses the three write commands before their bodies
  run.

### Reuse

Used, not reimplemented:

- `list_rules_service` and its `(priority, id)` contract;
- `remove_rule_service`, for every retirement;
- `get_account_by_name_service` and `account_has_children_service`;
- `post_entry` and `validate_lines`;
- `Reclassify`'s reversing-pair logic, factored into `_post_correction`
  rather than copied;
- the split refusal's reasoning;
- the bucket constants and the strict bucket lookup from
  `ListUnclassified`;
- the eager-loading shape of `unclassified_classifications_service`;
- `UnitOfWork` and the `crud_*` decorators;
- `_KohleCommand(writes=…)`;
- `tomllib`, `click.edit`, `click.confirm`, `tabulate`, `hashlib`,
  `tempfile`;
- `_refuse_if_unrepresentable`;
- the `MalformedStatementRow` error shape;
- the canonical-text storage contract of CS and BG.

Introduced for the next piece of work:

- **`conditions.py`** (`When`, `compile_when`) knows nothing of rules.
  `expected-payments` asks to recognise a payment by counterparty, IBAN and
  amount range, which is exactly this language. That inbox note already
  says the two may share matching.
- **`_post_correction`** is the one place a line moves between accounts
  after import.
- **The plan, prompt, then apply-with-base pattern** fits any later "edit X
  as a file" command (caps, sampling rules, accounts). It is not generalised
  now: there is one consumer, and the fingerprint is three lines.

### Extension points

- **Condition kinds are a closed set in `When`.** A new kind needs a field,
  a `KEYS` entry, and a parse, render and compile branch. Its contract:
  - render then parse is the identity;
  - equality is content identity;
  - stored text is user syntax, so a new kind needs no migration.

  Day-of-month conditions are a spec non-goal, and this is where they would
  go.
- **The ML phase** reads `classifications` (`proposed`, `matched_rule_id`,
  `rerun_rule_id`, `final`, `corrected`) and `rules.condition`. No plugin
  contract is introduced, since a classifier plugin is a non-goal.
- **`cli-command-naming`** may rename the commands. Use cases do not know
  the names. They appear only in the CLI, in `RulesChanged`'s and
  `ClassifyPlanChanged`'s messages, and in the file's header comment.
- **The TUI** can drive `ShowRules`, `PlanRuleFile`, `ApplyRuleFile`,
  `PlanClassifyRules` and `ApplyClassifyRules`, which have no CLI
  knowledge. The editor loop and banner are CLI-only. Editing rules from
  the TUI is a non-goal.
- **No other extension point.** Machine-readable output beyond the TOML is
  a non-goal.

### Build vs. buy

| Component | Decision | Evaluated, and what it could not do |
|---|---|---|
| TOML reading | **Buy:** `tomllib` (stdlib), with `parse_float=Decimal` | The spec names it. |
| TOML writing | **Build:** `toml_string`, `toml_decimal`, and two `When` renderers, about 60 lines | **tomli-w** gives no per-value layout control. It emits arrays of tables as `[[rule.when.any]]` sections and nested tables as `[rule.when.any.not]` headers, not the spec's one-line OR alternatives. It always writes basic strings, so every regex backslash doubles. **tomlkit** can build inline tables, but it is a style-preserving document library with its own parser, a second TOML parser beside `tomllib`. It has no exact-decimal value type, so it would need a float (forbidden) or a raw-text workaround. Either one is a new dependency for a fixed, tiny shape. Neither is installed (`uv.lock`). |
| Condition evaluation | **Build:** `compile_when` | Rule-engine libraries (`rule-engine`, `business-rules`, JSON-Logic ports) bring their own expression syntax and float numerics, and none has the spec's semantics: a missing counterparty, IBAN normalisation, an absolute-amount range. |
| Identity diff | **Build:** dict lookup on `(When, account_id)`, plus an LIS for "reordered" | `difflib.SequenceMatcher` aligns sequences by position and similarity, not by identity, and would still leave priority assignment to write. |
| Editor | **Buy:** `click.edit` | The editor must be resolved before calling it, because of its `vi` fallback. |
| Confirmation | **Buy:** `click.confirm(abort=True)` | |
| Fingerprint, recovery file | **Buy:** `hashlib.sha256`, `tempfile.mkstemp` | |
| Storage | **Build:** two columns | Rows and JSON are rejected in §2.2. |

### Abstractions introduced

| Abstraction | Forcing problem |
|---|---|
| `When` | A condition tree that compares by content (identity, duplicates, an unchanged file means no writes), renders canonically, and is the parse target of both the file and storage. One table-shaped dataclass, because a TOML table holds each key once. |
| `AmountRange` | "At least one end, low ≤ high, both exact" as one value, rather than two loose optionals on `When`. |
| `Direction` | A closed two-value set, as `Role` is in `sampling.py`. |
| `compile_when` / `Predicate` | Patterns are compiled once per import (the existing `CompiledRule` reason), with short-circuit evaluation and no second tree type. |
| `StoredRule` | ORM rows cannot cross the session (`list-rules`, `show-rules`, the plan), and the condition text must be parsed once. |
| `FileRule`, `RuleFile` | The parsed file carries positions for error messages, and the optional base. |
| `PlannedRule`, `RulePlan` | The summary must be shown before a separate apply transaction. The apply needs per-rule priorities and kept and retired sets. |
| `RerunMove` | The preview is shown before a separate apply, and the apply compares moves. |
| `_post_correction` | Two callers (`reclassify`, `classify-rules`) must post the identical reversing pair. |
| `update_rule_service`, `set_rerun_outcome_service`, `rerun_candidates_service` | Each is one new persistence operation. The update service's narrow signature is what makes condition immutability structural. |
| `rerun_rule_id` + CHECK | §7.1. |
| `MalformedRuleFile`, `RulesChanged`, `DuplicateRule`, `ClassifyPlanChanged` | Distinct user messages, and the edit loop branches on the first two. |
| `base` in the file | §6. |

**Deliberately not introduced:**

- a condition class hierarchy or visitor;
- a general TOML serialiser;
- a `rule_conditions` table;
- a rules version counter, setting or lock table;
- a generic "edit as file" framework;
- a `source` enum on `Classification`;
- reviving retired rules;
- a partial unique index on live rules;
- any rule-evaluation optimisation.

---

## 14. Alternatives rejected

- **One column per condition.** It cannot hold OR or NOT (the spec says so).
- **Conditions as rows.** §2.2: a tree rebuild, REAL-typed bounds, and SQL
  queries nobody needs.
- **JSON storage.** §2.2, CS §14 and BG §13.
- **The whole rule (account, note, when) as one TOML text.** The account
  would lose its foreign key, and the mutable note would sit inside the
  immutable text.
- **tomli-w or tomlkit.** See Build vs. buy.
- **Rule ids in the file** (an `id = 7` key). The spec forbids it, and it
  would make identity positional or user-editable.
- **Identity by position.** Moving a rule would retire it.
- **Always renumbering priorities.** It writes on every apply and turns a
  one-rule insert into N audit entries. It also breaks "an unchanged file
  writes nothing" on any ledger whose priorities are not already 100, 200,
  300 and so on.
- **Renumbering priorities in the migration** to make them evenly spaced.
  It would avoid the one-time renumber on tied ledgers (§5.3), but the
  migration should change only what the spec asks. That renumber is
  visible, and correct, in the audit trail.
- **Retiring stored duplicates in the migration.** That is a silent change
  to the user's data with no audit trail (§2.5).
- **A partial unique index on `(condition, account_id) WHERE deleted_at IS
  NULL`.** Creating it would fail on a ledger that already holds
  duplicates. It also compares text, while identity is structural.
- **The base as a TOML comment.** Comments are not data, editors and tools
  strip them, and reading one needs a regex over the raw text.
- **The file's mtime as the "rendered at" marker.** Editing the file
  changes its mtime, so a concurrent `add-rule` during the edit would be
  missed.
- **A stored rules version (a counter or a setting).** Every rule write
  would also have to bump it, `add-rule` and `remove-rule` included. The
  fingerprint is derived and costs no write.
- **A transaction held open across the editor or the prompt.** §6.
- **Overwriting `proposed_account_id` and `matched_rule_id` on a
  `classify-rules` move.** It breaks `reclassify` and `split-line`, which
  find the original line through `proposed_account_id` (§7.1), and erases
  the import-time record.
- **Setting `matched_rule_id` to the rerun rule, plus a flag.** It breaks
  the invariant that `matched_rule.account_id` equals `proposed_account_id`,
  and makes "which rule, when" an inference.
- **A `source` enum (`import`, `rerun`, `human`) in place of `corrected`.**
  It migrates existing data, and it cannot say "moved by a rerun, then
  corrected by a human" without losing one of the two.
- **A second `Classification` row per move.** `uq_classification_journal_entry`
  and EC §7.3 rule it out.
- **Reclassifying from `apply-rules` (a `--reclassify` flag).** The spec
  keeps the two commands apart, so that changing rules never reclassifies.
- **`classify-rules` covering split lines** by moving only the own share.
  It would be a split-aware correction, which `reclassify` deliberately
  does not have (EC §5.4).
- **Sorting `any` alternatives canonically.** It would reorder the user's
  text on every round trip.
- **Stripping patterns in the file as `add-rule` does.** A quoted TOML
  string's spaces are deliberate.
- **Treating a zero amount as `in`** (as the import's income-bucket
  fallback does). A zero line moves no money in either direction (§16 item
  5).
- **Keeping `add-rule --priority`.** §16 item 1. The planner tolerates any
  priorities, so restoring the flag costs nothing if the user wants it.
- **A mirrored compiled tree** in place of closures. §3.5.
- **The editor banner at the bottom of the buffer.** It is not seen in a
  long file. A top banner of variable height would shift syntax-error line
  numbers (§10.1).

---

## 15. Slice order and per-slice files

**The order is unchanged:** 082 → 083 → 084 → 085 → 086 → 087 → 088 → 089.
087 and 088 could come earlier, since their declared dependencies are 084
and 082. Keeping 088 after 085 means `classify-rules` passes the signed
amount from its first commit, instead of 085 having to edit it. No review
stop is needed inside the run, because every slice leaves a coherent, tested
state.

**What moves between the issues:**

1. **The `note` column moves into 082's migration.** Issue 082 exists so
   that "later slices can add conditions without another storage change".
   Notes are a storage change too, and 083 renders them while 084 updates
   them. One migration for `rules` is simpler than two.
2. **082 removes `add-rule --priority`.** Issue 082's own criterion ("appends
   the new rule at the end of the order") requires it. This depends on the
   answer to §16 item 1.
3. **`base` is rendered in 083 and checked in 084.** It is part of the file
   format from the first rendering, so 083's output is final.
4. **The `add-rule` duplicate refusal lands in 084,** with content identity
   and the file's duplicate check. It is an addition to issue 084's
   criteria.
5. **Each slice fixes the README statements it makes false;** 089 writes
   the section (§12).

### 082: rules as condition trees

- **Production:**
  - `conditions.py` with `When(any_field)`, `toml_string`,
    `render_when_inline`, `parse_stored_when` and `compile_when`;
  - `models.py`: `Rule.condition`, `Rule.note`, no `pattern`, no priority
    default, and the `__repr__`;
  - `rules.py`: `StoredRule`, `stored_rules`, `CompiledRule.holds`,
    `compile_rules`, `match_rule` (no amount yet), `AddRule` (end of order),
    and `ListRules` returning `StoredRule`;
  - `rule_services.add_rule_service(ctx, condition, account_id, priority,
    note=None)`;
  - `journal.py`'s use of `stored_rules`;
  - the CLI's `add-rule` (no `--priority`) and `list-rules` columns;
  - the migration and `HEAD_REVISION`;
  - the README lines that 082 makes false.
- **Tests:**
  - `test_rule_matcher.py` rebuilt on `StoredRule`/`When`, every existing
    case kept;
  - `test_conditions.py` for `any_field` and the quoting table;
  - `test_rules.py` and `test_rule_services.py` for the new signatures and
    end-of-order;
  - `test_cli.py` for the `list-rules` header `["id", "account",
    "conditions"]` and the `add-rule` output;
  - `test_migration_downgrade.py`: conversion, round trip and refusal;
    update the two tests that insert `pattern` at head;
  - a migrated-ledger equivalence test (§17.5);
  - `test_schema_check.py`'s head pin.

### 083: `show-rules`

- **Production:** `render_rule_file`, `rule_set_base`, `ShowRules`, the CLI
  command, and the README stub.
- **Tests:**
  - render determinism: the same set twice gives the same text;
  - `tomllib` parses the output into the expected dicts;
  - no ids in the output;
  - the base is present, and is a function of content only;
  - empty set;
  - `_read_argv["show-rules"]`.

### 084: `apply-rules` and content identity

- **Production:**
  - `When` gains `description`, `counterparty` and `iban` (with
    `normalise_iban`);
  - `parse_when` for those keys;
  - `FileRule`, `RuleFile`, `parse_rule_file`;
  - `PlannedRule`, `RulePlan`, `plan_rule_changes`, the priority
    assignment and the LIS;
  - `PlanRuleFile` and `ApplyRuleFile`;
  - `update_rule_service`;
  - `MalformedRuleFile`, `RulesChanged`, `DuplicateRule`, and the
    `AddRule` refusal;
  - the CLI's `apply-rules` and summary;
  - `_WRITE_ARGV["apply-rules"]`, which needs an existing file argument,
    because click opens `FILE` before `invoke` runs;
  - the README stub.
- **Tests:** §17.2–§17.4.

### 085: amount and direction

- **Production:** `AmountRange`, `Direction`, `toml_decimal`, their parse,
  render and compile branches, and `match_rule(..., amount)` with the import
  passing `row.amount`.
- **Tests:**
  - parse rejections: bool, nan/inf, negative, `min > max`, `{}`, an
    unknown key in `amount`;
  - exact-decimal round trips (`400.10`);
  - zero-amount direction;
  - the spec scenario end to end (§17.4).

### 086: `any` and `not`

- **Production:** `any_of` and `not_`, `render_when_lines`'s multi-line
  `any`, and the nested inline `any`.
- **Tests:**
  - empty `any`, empty `not` and an empty item are rejected with their key
    paths;
  - nesting round trips;
  - `not` over a missing counterparty;
  - the Groceries example;
  - short-circuit (§17.1);
  - `show-rules | apply-rules --yes` reports no changes on a nested set.

### 087: `edit-rules`

- **Production:** the CLI's `edit-rules`, `_strip_banner`, `_with_banner`,
  the editor resolution and the recovery file.
- **Tests:** §17.6.

### 088: `classify-rules`

- **Production:**
  - the migration and `HEAD_REVISION`;
  - `Classification.rerun_rule_id`, the CHECK, and `matched_rule`'s
    `foreign_keys=`;
  - `rerun_candidates_service` and `set_rerun_outcome_service`;
  - `_post_correction`, extracted from `Reclassify` with its behaviour
    unchanged;
  - `RerunMove`, `_rule_amount`, `_plan_moves`, `PlanClassifyRules`,
    `ApplyClassifyRules`;
  - `ClassifyPlanChanged`;
  - the CLI command;
  - `_WRITE_ARGV["classify-rules"]`;
  - the README stub.
- **Tests:** §17.7.

### 089: docs

As in §12. A test, or a review check, makes sure no README or `AGENTS.md`
sentence says a rule is a single regular expression.

---

## 16. Gaps in the spec, and points for the user

1. **`add-rule --priority` against "adds the new rule at the end of the
   order".**
   - Today `add-rule` takes `--priority`, default 100, and `list-rules`
     shows the priority. The spec says `add-rule` keeps its single-pattern
     form and appends, and that `list-rules` shows id, account and
     conditions, with no priority.
   - Keeping the flag would contradict "at the end" whenever it is used,
     with numbers the user can no longer see.
   - **Design: remove `--priority`; order is changed through the file.**
     This breaks scripts that pass it, such as the README example. If the
     user wants to keep it, restoring it is cheap: the planner tolerates
     any priorities (§5.3).
2. **Duplicate rules already stored break the round trip.** The spec
   rejects a file with two identical rules, and today's ledger may hold
   such a pair, which the migration preserves.
   - **Design:** the first `show-rules | apply-rules --yes` on such a ledger
     is rejected, naming both positions. The user deletes one line, and from
     then on the guarantee holds.
   - `add-rule` newly refuses a duplicate of a live rule. That is a small
     behaviour change to an "unchanged" command.
   - The alternative, the migration retiring dead duplicates, changes user
     data without an audit entry (§2.5).
3. **"Refuse when the stored rules changed after the file was rendered"**
   needs the file to say what it was rendered from. The design adds a
   top-level `base` key, which is not in the spec's layout.
   - A file without `base` is applied against the current rules with no
     check. That is how an empty file can retire everything.
   - Deleting the `base` line is the documented way to apply a stale file
     on purpose.
4. **The spec's list of rejections is not exhaustive.** The design also
   rejects:
   - wrong value types;
   - a `direction` other than `in`/`out`;
   - negative or non-finite bounds;
   - `amount = {}`;
   - empty or whitespace-only patterns;
   - an IBAN that is not letters and digits;
   - an empty table inside `any`;
   - `rule` or `base` of the wrong shape.

   Each one names the position and the key.
5. **A zero amount** satisfies neither `direction = "in"` nor `"out"`. The
   import files a zero line under `Unclassified Income`, but that is a
   bucket fallback, not a direction.
6. **Summary categories.** The spec lists added, retired, unchanged and
   reordered. The design adds "note changed", so a note-only edit is not
   confirmed against a summary that shows nothing. "Reordered" means the
   minimal set of moved rules, not every rule whose index shifted.
7. **`classify-rules` skips split lines.** `reclassify` refuses them,
   because the bucket holds only the own share. The spec's "lines still
   sitting in the unclassified buckets" does not mention splits. The design
   skips them silently, and the README says so.
8. **A concurrent change during `edit-rules`** would lose the user's edits.
   The design saves them to a temporary file and names it in the error.
   That goes beyond the spec, which only asks for the refusal.
9. **Declining a prompt exits 1** (`Aborted!`, click's convention). The spec
   asks for non-zero on errors and says nothing of declining.
10. **The `classify-rules` preview shows the signed amount,** the value the
    `amount` and `direction` conditions saw. `list-unclassified` shows the
    unsigned line value. The direction is visible in both through the
    bucket name.
11. **`apply-rules -` reads stdin.** It needs `--yes`, because the prompt
    would read the same exhausted stdin.

---

## 17. Testing notes

**Layers.** Layer 1 is pure, with no fixture. Layer 2 is a use case against
the `session` or `session_factory` fixture. Layer 3 is the CLI through
`CliRunner`. There is no property-testing library in the project, so the
round trips are table-driven.

### 17.1 `conditions.py` (layer 1, `tests/test_conditions.py`)

- **Quoting.** For each string in a table (plain, `\d{4}`, `it's "x" \d`,
  tab, newline, DEL, NUL, `ü`, a lone `'`, a lone `"`, a lone `\`), check
  that `tomllib.loads("x = " + toml_string(s))["x"] == s`, and that the
  form chosen is the expected one: basic, literal or escaped.
- **Decimals.** `toml_decimal` maps `400`, `400.0`, `4E+2`, `400.50`,
  `0.000001`, `-0` and `0.00` to `400`, `400`, `400`, `400.5`, `0.000001`,
  `0`, `0`, and each output parses back numerically equal.
- **Round trip.** For a table of `When`s (one per key, combined keys,
  nested `any`/`not` to depth 3), check `parse_when(tomllib(render)) ==
  when` for both the inline and the line forms.
- **Key order does not matter.** Two files that differ only in key order
  parse to equal `When`s. `iban = "de89 3704 …"` equals `iban =
  "DE893704…"`.
- **Each rejection in §3.3,** asserting the key path in the error.
- **Semantics:** one test per row of §3.2; `None` counterparty against
  `counterparty`, `iban`, `not` and `any_field`; amount bounds inclusive at
  both ends and open on either; zero against both directions.
- **Short-circuit.** Pass a stub counterparty whose `name` and `iban`
  properties raise `AssertionError`, with `When(description="x",
  counterparty="y")` on a description that does not match, and with
  `When(any_of=(When(description="match"), When(counterparty="y")))` on
  one that does. Neither touches the stub.
- **The Groceries example from the spec:** `rewe` matches; `edeka` without
  `pfand` matches; `edeka` with `pfand` does not.

### 17.2 The rule file and the planner (layer 1, `tests/test_rule_file.py`)

- **Every rejection in the spec and §16 item 4,** asserting `str(err)`
  starts with `rule N, <key>:`. TOML syntax errors carry the line.
- **Duplicates name both positions.**
- **The planner:**
  - an unchanged set gives an empty plan;
  - a note-only change gives `renoted` and one update;
  - a moved rule gives `reordered == {id}`, and moving the top rule to the
    bottom reports one rule;
  - a changed condition or account gives one retired and one added;
  - an empty file retires all;
  - legacy stored duplicates keep the first and retire the second.
- **Priority assignment:**
  - insert at the front, middle and end without touching kept priorities;
  - an insert between tied priorities falls back to renumbering, and only
    changed priorities appear in `updates`;
  - a reorder renumbers;
  - the resulting `(priority, id)` order equals file order in every case.
    This is the invariant, so assert it directly, with simulated new ids
    larger than the existing ones.

### 17.3 Use cases (layer 2)

- **`ApplyRuleFile`:**
  - one `OperationGroup` holds every write;
  - an empty plan leaves none;
  - a stale base gives `RulesChanged` with nothing written;
  - an account that gains a child between plan and apply makes the apply
    fail with nothing written;
  - a fault injected on the second `add_rule_service` call (monkeypatched)
    rolls everything back;
  - kept rules keep their ids and `Classification.matched_rule_id` rows are
    untouched;
  - no `journal_entries` or `classifications` row changes.
- **`AddRule`:** appends after the last live rule, and refuses a duplicate
  of a live rule but not of a retired one.

### 17.4 CLI (layer 3, `tests/test_rules_cli.py`)

- **`show-rules` then `apply-rules --yes`** prints `No changes`, exits 0,
  and leaves the `OperationGroup` count the same. This is the spec's
  testable claim.
- **The spec scenario.** `apply-rules --yes` sets two rules on one IBAN
  (`amount = { min = 400, max = 600 }` and `{ min = 1500 }`). A statement
  with an outgoing 500 and an outgoing 2000 lands on the two accounts.
- **Prompts:** declining with `input="n\n"` exits 1 and writes nothing;
  `--yes` writes; a file with an error exits 1 with the positioned message.
- **Readers:** `apply-rules`, `edit-rules` and `classify-rules` are refused
  on a reader, and `show-rules` runs there.

### 17.5 Migration (`test_migration_downgrade.py`, plus an equivalence test)

- **Conversion.** At `BEFORE_RULE_CONDITIONS` (the revision 082 replaces),
  insert live and retired rules whose patterns hold quotes, backslashes and
  both quote kinds, plus a classification naming one of them. After
  `upgrade head`:
  - ids, priorities, accounts and `deleted_at` are the same;
  - `condition` parses to `When(any_field=pattern)`;
  - the classification's `matched_rule_id` is unchanged.
- **Downgrade:** round-trips when everything is a single `any_field` with no
  note; refuses with a note set, or with a non-`any_field` condition, and
  leaves the schema untouched.
- **Equivalence** (spec: "classifies exactly as it would have before").
  - Build a ledger at the previous revision with rules covering a
    description hit, a counterparty-name hit, an anchored IBAN pattern,
    and two rules tying on priority.
  - Migrate it, and import a statement through the CLI.
  - Assert each row's account and `matched_rule_id`. The oracle is the
    expected table written from the pre-feature semantics, checked in
    before 082 changes the matcher (BG §16.1's captured-oracle practice).
- **The 088 migration:** the column, the FK and the CHECK exist; the
  downgrade refuses when `rerun_rule_id` is set.

### 17.6 `edit-rules` (layer 3)

Tests monkeypatch `click.edit` with a scripted sequence of returns, and
record the texts it was given and the `editor=` argument.

- With no `VISUAL` or `EDITOR`: the clear message, exit 1, and `click.edit`
  is never called.
- `VISUAL` wins over `EDITOR`.
- Returning `None` the first time prints `No changes; nothing applied`.
- A bad file, then `None`:
  - the second text starts with the two-line banner naming the error;
  - for a syntax error, the reported line number points at the offending
    line in that second text;
  - nothing is written.
- A bad file, then a fixed file, then confirm: the rules are applied, and
  the banner is stripped before parsing.
- A valid file with `n` at the prompt writes nothing.
- An `add-rule` slipped in by the fake editor, through a second session
  before it returns, gives `RulesChanged`. The recovery file exists and
  holds the user's text.

### 17.7 `classify-rules` (layer 2 and layer 3, `tests/test_classify_rules.py`)

- **Eligibility.** None of these is moved even when a rule matches:
  - a line a rule matched at import;
  - a line a rule sent into a bucket;
  - a line a human reclassified, including into a bucket;
  - a line a previous run moved;
  - a split line;
  - a line whose matching rule targets the bucket it is already in.
- **The record:** `proposed_account_id` and `matched_rule_id` are
  unchanged, `final_account_id` is the target, `corrected` is false, and
  `rerun_rule_id` is the rule.
- **The correcting entry:** dated at the original date, described as
  `Classify: …`, and leaving the balances where `reclassify` would.
- **Later corrections still work.** `reclassify` of a moved line succeeds,
  reverses out of the target and sets `corrected`. `split-line` of a moved
  line takes the shares out of the target.
- **The amount:** an `amount` and `direction` rule matches a past outgoing
  line exactly as at import.
- **Atomicity:** one `OperationGroup`; a fault on the second move rolls back
  the first.
- **The guards:** a moved-meanwhile line (an import or reclassify between
  plan and apply) gives `ClassifyPlanChanged`; a non-leaf target fails at
  plan, before any preview.
- **The CLI:**
  - preview columns;
  - an empty plan prints the message and exits 0;
  - declining exits 1 with nothing written;
  - `--yes` applies;
  - `apply-rules` and `add-rule` never change `classifications` or
    `journal_entries` counts.

---

## 18. Observation outside this spec

**A latent bug in `ListUnclassified` (not fixed by this design; it belongs
in a `change`).**

- **The cause.** `_to_unclassified_line` picks the line by
  `final_account_id`. A line that a rule classified at import and a human
  then reclassified *into* a bucket has its final account on the bucket,
  but the original entry has no line there.
- **The effect.** `next(...)` raises `StopIteration`.
  `DbTransaction.execute` catches it and returns it as the error, so
  `list-unclassified` fails with an empty `Error:` message.
- **The likely fix.** Pick the line by `proposed_account_id`, which always
  exists in the original entry and carries the same value.
- **Why `classify-rules` is not affected.** It excludes corrected lines
  before mapping.
