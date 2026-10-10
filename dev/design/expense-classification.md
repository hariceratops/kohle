# Design: Automatic expense classification

Spec: `dev/specs/expense-classification.md` (frozen)
Issues: `dev/issues/013`–`017`

Layering per `AGENTS.md` stays `app -> use_cases -> services ->
infrastructure/domain`. Only services touch a `Session`. Functions return
`Result[T, E]`; domain errors are `Exception` subclasses used as values.

---

## 1. Summary of the shape

| File | Change |
|---|---|
| `kohle/domain/models.py` | `JournalEntry.counterparty_name` / `.counterparty_iban`; new `Rule` and `Classification` |
| `kohle/domain/domain_errors.py` | `RuleError` / `ClassificationError` families, three union aliases, `__str__` on the two dataframe errors |
| `kohle/infrastructure/crud.py` | `crud_update` and `crud_delete`, from one `_record_write(action)` factory |
| `kohle/services/journal_services.py` | `Counterparty`; `add_journal_entry_service` persists it |
| `kohle/services/rule_services.py` | **new** — rule CRUD, evaluation-ordered listing |
| `kohle/services/classification_services.py` | **new** — classification insert, lookup by entry, unclassified query, outcome update |
| `kohle/use_cases/journal.py` | `post_entry` gains a counterparty; `ImportStatement` matches, posts through `post_entry`, and records a classification per row; importer schema columns renamed |
| `kohle/use_cases/rules.py` | **new** — `AddRule`, `ListRules`, `RemoveRule`, and the pure matcher |
| `kohle/use_cases/classification.py` | **new** — `UnclassifiedLine`, `ListUnclassified`, `Reclassify` |
| `kohle/plugin/importer_plugin.py` | contract: required columns, their dtype, and the omission rule |
| `kohle/app/plugins/kohle_deutsche_bank_importer.py` | keep `beneficiary`, rename to the contract's column names, force string dtype |
| `kohle/app/cli/cli.py` | `add-rule`, `list-rules`, `remove-rule`, `list-unclassified`, `reclassify`; a counterparty column on `entries-in-period`; delete the stale issue-011 comment |
| `alembic/versions/` | **three** migrations, one per schema-bearing slice (§8) |
| `README.md` | the plugin contract's column list; the five new commands |

Two new use-case modules rather than growing `journal.py` further. The
existing design (§1) argued against a `reporting.py` because
`QueryJournalByPeriod` already lived in `journal.py` and splitting would
scatter reads across two files. That argument does not transfer: `Rule` and
`Classification` are new nouns with their own tables and their own CLI verbs,
and `use_cases/` is already one-module-per-noun (`accounts`, `units`,
`operations`, `journal`). Putting them in `journal.py` is what would be the
parallel structure.

**Import direction is fixed by one constraint and is not negotiable:**
`classification.py` imports `post_entry` from `journal.py`, so `journal.py`
must never import `classification.py`. `ImportStatement` therefore reaches
`add_classification_service` in the *services* layer directly, not through a
use case. `journal.py` importing the matcher from `rules.py` is fine and has
precedent — it already imports `get_or_create_unit` from `use_cases/units.py`.

---

## 2. The four questions the spec left open

### 2.1 Pattern language: Python regular expressions

**Chosen: `re`, compiled with `re.IGNORECASE`, matched with `.search()`
against each of `description`, `counterparty_name` and `counterparty_iban`
independently.**

Issue 014's acceptance constraint is the deciding factor: *a malformed
pattern must be rejected when the rule is created.* Regex is the only one of
the three candidates where that constraint does real work — `re.compile` at
`AddRule` time is the whole check, it costs one line, and it produces a
message a user can act on:

```
>>> re.compile("REWE[")
re.error: unterminated character set at position 4
```

(verified, CPython 3.12.3). `InvalidRulePattern` carries the pattern and
`str(err)`, so `add-rule 'REWE[' Groceries` fails with *unterminated
character set at position 4* and no rule is created.

Matching per field rather than against a concatenation is what makes anchors
useful. `^DE89370400440532013000$` means "this exact counterparty IBAN", which
is the single highest-value rule shape for a bank ledger — a landlord, an
employer, a utility. Against a joined haystack, `^` and `$` would mean "start
and end of the blob", which is useless, and users would be pushed toward
unanchored substrings for everything.

Case-insensitive by default because bank exports are inconsistently cased
(`REWE SAGT DANKE`, `Rewe Markt GmbH`) and a user writing `rewe` means both.
Case sensitivity stays reachable: Python 3.11+ supports inline local flags, so
`(?-i:REWE)` is case-sensitive inside an otherwise-insensitive pattern
(verified). One default, one documented escape hatch, no second column.

**No normalization of the haystack.** Bank descriptions contain runs of
spaces and the temptation is to collapse them before matching. Rejected: the
string `list-unclassified` prints would then differ from the string the
pattern is applied to, and a user writing a rule from that output would get
silent non-matches with nothing to look at. What you see is what is matched.

**Rejected: plain substring.** It satisfies issue 014's constraint only
vacuously — every string is a well-formed substring pattern, so "rejected at
creation" would be an empty promise, and the first real thing a user wants
(`REWE|ALDI|LIDL`, or an exact IBAN) is inexpressible. Picking the option that
makes the acceptance criterion unfalsifiable is picking it for the wrong
reason.

**Rejected: a small DSL** (`description contains "REWE" and iban starts-with
"DE89"`). It is cheaper here than it looks — `pyparsing` is already a
dependency, used by the Deutsche Bank importer — and that is exactly why it
needs an explicit refusal rather than silence. It buys field targeting and
boolean combination over regex; field targeting is already covered by
anchoring plus per-field matching, and boolean combination over a *single*
line's fields is rare enough that alternation covers the real cases. Against
that: a grammar, an evaluator, an error-reporting story, a section of README,
and a second pattern language in a codebase whose sole user reads regex
natively. The forcing problem does not exist yet.

**Rejected: a `field` column on `Rule`** (`description` | `counterparty_name`
| `counterparty_iban`), so a pattern targets one field. It is the natural
first instinct and it is worth saying why it is not here: with per-field
`.search()` the OR over three fields is already the behaviour a user wants,
and the failure it protects against — a pattern intended for an IBAN
accidentally matching a description — is not a failure, because a description
containing that IBAN *is* the same counterparty. The column would add a
required argument to `add-rule` to prevent a harmless case.

**Accepted cost, recorded: catastrophic backtracking.** `re` has no timeout,
so a pathological pattern (`(a+)+$`) against a long description can hang an
import with no progress and no error. Not mitigated: patterns are written by
the only user of this ledger, descriptions are a couple of hundred characters,
and the alternatives are a new dependency (`regex`, which has a timeout) or a
subprocess. The failure mode is survivable, and the reason is worth knowing:
`KeyboardInterrupt` is a `BaseException`, so it is *not* caught by
`DbTransaction.execute`'s `except Exception`; it propagates, the `finally`
closes the session, the transaction was never committed, and the ledger is
untouched. Ctrl-C during a wedged import loses nothing.

### 2.2 The classification record: `Classification` / `classifications`

```python
class Classification(base, Archivable):
    __tablename__ = "classifications"

    id:                  Mapped[int]        = mapped_column(Integer, primary_key=True)
    journal_entry_id:    Mapped[int]        = mapped_column(ForeignKey("journal_entries.id"), nullable=False)
    proposed_account_id: Mapped[int]        = mapped_column(ForeignKey("accounts.id"), nullable=False)
    matched_rule_id:     Mapped[int | None] = mapped_column(ForeignKey("rules.id"), nullable=True)
    final_account_id:    Mapped[int]        = mapped_column(ForeignKey("accounts.id"), nullable=False)
    corrected:           Mapped[bool]       = mapped_column(Boolean, nullable=False, default=False)

    entry:          Mapped["JournalEntry"] = relationship("JournalEntry")
    matched_rule:   Mapped["Rule | None"]  = relationship("Rule")
    final_account:  Mapped["Account"]      = relationship("Account", foreign_keys=[final_account_id])

    __table_args__ = (
        UniqueConstraint("journal_entry_id", name="uq_classification_journal_entry"),
    )
```

The name is the spec's own and there is no better one: "classification" is
already the vocabulary of the feature and of the two bucket accounts. The
plural table name follows every other table.

**`UniqueConstraint("journal_entry_id")` is the load-bearing part.** It is
what makes "the classification of this line" a phrase with one referent, which
is what `reclassify` (§2.4, §7) needs to update and what `list-unclassified`
needs to avoid double-reporting. Without it the table is an append-only log
and every read needs a max-per-entry subquery — see the rejected alternative
in §7.3.

**Two explicit `foreign_keys=` on the relationships** because
`proposed_account_id` and `final_account_id` both point at `accounts`;
SQLAlchemy cannot infer the join otherwise. Only `final_account` gets a
relationship — `proposed_account_id` is never displayed by this slice, and
adding an unused eager-loadable relationship is an invitation to a lazy load
after the session closes.

**`Archivable`** for consistency with `Account`, `Unit`, `JournalEntry` and
`Rule`. `deleted_at` is never written for this table, and must not be: a
deleted classification is a hole in the training set. That is a convention,
not a constraint, and it is the same convention every other table except
`rules` currently follows.

**At import, `proposed_account_id == final_account_id` for every row**, on
both the matched and the fall-through path. The two columns only diverge after
a `reclassify`, and that divergence is the entire record. Stated because
someone reading the insert will see two columns getting the same value and
try to collapse them.

**`corrected` is not quite derivable from `proposed != final`,** which is why
it stays a column rather than a property: reclassifying a line to the account
it is already on, or a correction chain `A → B → A`, both leave
`proposed == final` on a row a human demonstrably touched. It is also the
field the spec fixes by name.

`corrected` is written by this slice and read by nothing in it — no query in
§6 or §7 filters on it. That is deliberate and worth saying out loud rather
than looking like an oversight: it is the label, and the consumer is the ML
phase in a later spec.

### 2.3 Priority and tie-breaking: confirmed, as a total order

**`ORDER BY priority ASC, id ASC`, first match wins, evaluation stops there.**

The spec's default is confirmed, with one thing made precise: the tie-break is
`id`, not "insertion order", because `id` is the autoincrement primary key and
is therefore a *total* order — two rules can never compare equal, so
"deterministic on every run" (issue 014) is a property of the ORDER BY rather
than of how SQLite happens to return unordered rows.

`list-rules` renders `id`, `priority`, `pattern`, `account` in exactly that
order, so the evaluation order is not merely deterministic but visible, which
is the other half of issue 014's criterion.

**First match wins, not best match.** The matcher returns the first
`CompiledRule` that hits and does not look at the rest. That is what makes
`matched_rule_id` a single well-defined value; a "collect all matches" matcher
would need a second rule to pick one, which is the same decision moved
somewhere less visible.

`--priority` defaults to **100**, leaving room to insert both before and after
an existing rule without renumbering and without negative numbers. A user who
never passes `--priority` gets pure insertion order, which is the predictable
default.

**Rejected: most-specific-wins (longest pattern).** Pattern length is not
specificity for regexes — `.*` is shorter than `^REWE` and matches strictly
more — so the rule would be actively misleading, and it would silently reorder
the rule set whenever a pattern was edited.

**Rejected: refuse the import when two rules match one row.** It converts a
resolvable ambiguity into a failed statement import, and the whole premise of
the slice is auto-apply. A user with overlapping rules (`^AMZN` → Shopping and
a catch-all `.` → Misc) has written something perfectly sensible.

**Rejected: a unique constraint on `priority`.** It forces renumbering to
insert a rule between two others, which is the classic reason ordering columns
get sparse defaults, and it buys nothing that `id` as tie-break does not
already give.

### 2.4 `reclassify` identifies a line by **journal entry id**

```
kohle-cli reclassify ENTRY_ID ACCOUNT
```

`list-unclassified` prints the entry id in its first column, which satisfies
issue 017's constraint directly. The same principle applies one issue earlier:
`list-rules` prints rule ids because `remove-rule` takes one.

**Rejected: the entry `reference`.** For imported rows it is a 64-character
sha256 hex digest. Printing it in a `tabulate` column would dominate the
output and nobody is going to retype it. A short prefix with a uniqueness
check is a second identifier scheme invented for one command.

**Rejected: the classification id.** It is also a small integer, which is
precisely the problem: two small-integer id spaces over the same conceptual
thing, where passing one where the other was meant resolves *successfully* to
the wrong row. Entry ids are the id space every other listing can and will
show, and `reclassify 42` on a hand-entered entry that has no classification
fails loudly with `NoClassificationForEntry(42)` rather than silently hitting
some other line.

**Rejected: browse `entries-in-period` first, then reference the line by
date + description.** Not unique, and the spec's own analogy to `record`'s
flag shape does not extend to identity.

---

## 3. Issue 013 — counterparty through the import path

### 3.1 Schema

Two nullable columns on `journal_entries`:

```python
counterparty_name: Mapped[str | None] = mapped_column(String, nullable=True)
counterparty_iban: Mapped[str | None] = mapped_column(String, nullable=True)
```

`None` for `record` / `record-split`, which have no counterparty concept. No
placeholder, no empty string: `''` and "unknown" would both be values a rule
could match, and `NULL` is the only representation that cannot be matched by
accident.

No `UNIQUE`, no FK to `accounts`. A counterparty is a string a bank sent, not
an entity in this ledger. Modelling counterparties as accounts is a real
future direction (the vision document already says "eventually people"), and
the two nullable columns are exactly what a later migration would read to
build them.

### 3.2 `Counterparty`, and where it lives

```python
@dataclass(frozen=True, slots=True)
class Counterparty:
    name: str | None
    iban: str | None
```

**In `kohle/services/journal_services.py`, beside `LineSpec`,** for the same
reason `LineSpec` is there: it is a value a service signature takes, and a
use case importing from services is with the grain of the layering while the
reverse is not.

**Forcing problem:** the pair travels through four signatures — the dataframe
row, `post_entry`, `add_journal_entry_service`, and the matcher — and as loose
parameters that is three adjacent `str | None` arguments (description, name,
iban) in the matcher's signature. Transposing name and iban there type-checks
and silently matches the wrong fields against the wrong patterns, with no
error and no test that would obviously catch it. One value makes the
transposition unexpressible. This is *not* `CrossUnitLine`'s argument —
name-without-iban and iban-without-name are both perfectly valid — so the
justification is transposition safety alone, and that is enough.

`post_entry` gains `counterparty: Counterparty | None = None`. The default
keeps `RecordJournalEntry`, `RecordSimpleEntry` and `RecordSplitEntry`
untouched at their call sites and stores `NULL` in both columns, which is
issue 013's second criterion falling out rather than being implemented.

### 3.3 The importer plugin contract

The returned dataframe must carry five columns:

| column | dtype | meaning |
|---|---|---|
| `description` | string | free text from the statement |
| `amount` | float | signed; negative is money leaving the account |
| `date` | datetime | booking or value date, plugin's choice |
| `counterparty_name` | **string** | who the other side was |
| `counterparty_iban` | **string** | the other side's IBAN |

Renamed from the current bare `iban`, deliberately. `iban` is ambiguous
against `Account.iban` — the imported account's *own* IBAN — and this is the
counterparty's. The contract is changing anyway and there is exactly one
plugin, in-repo.

**How a plugin that cannot supply a counterparty must behave — the answer to
issue 013's third criterion.** The column must be **present and empty**, never
absent:

```python
df.assign(counterparty_iban=pd.Series(pd.NA, index=df.index, dtype="string"))
```

- **Absent column → hard failure.** `validate_df_schema` already returns
  `DataframeMissingColumn` before a single row is touched, so a plugin author
  who forgets learns on the first import, with the column named. This is what
  "omission must not be silent" buys: the alternative — treating a missing
  column as all-null — is precisely the state where a rule quietly stops
  matching and nothing anywhere says why.
- **Present with `pd.NA` → fine**, stored as `NULL`. Per-row absence is
  normal and honest: an ATM withdrawal has no beneficiary, a card payment
  usually has no counterparty IBAN.
- **A whole-format absence is a one-line, visible statement** in the plugin
  that it has nothing, rather than an omission indistinguishable from a bug.

**The dtype clause is not pedantry — it is a latent bug this slice would
otherwise walk into.** `validate_df_schema` checks `is_string_dtype`, and on
pandas 3.0.0 (verified in this venv):

| column contents | dtype | `is_string_dtype` |
|---|---|---|
| `['a', None, 'b']` from `read_csv` | `str` | True |
| a CSV column that is empty on every row | `float64` | **False** |
| `pd.NA`-filled, `dtype="string"` | `string` | True |

An entirely empty text column reads back as `float64`, so a statement where
*no* row has a counterparty IBAN fails schema validation with
`DataframeColumnTypeMismatch({'counterparty_iban': 'float64'})` — a confusing
error about a column the user never sees. **This already affects the current
`iban` column**; the slice inherits it and fixes it by making
`.astype("string")` part of the contract, which is stable under all-NA. The
Deutsche Bank importer does the cast; the contract's docstring and the README
state it.

`DataframeMissingColumn` and `DataframeColumnTypeMismatch` get `__str__`
methods. They are plain dataclasses today, so the CLI's `str(err)` prints
`DataframeMissingColumn(columns=['counterparty_name'])`. Readable, but this is
the one error a plugin author is guaranteed to hit and the message is the
contract's whole enforcement mechanism.

### 3.4 The Deutsche Bank importer

Two changes, both at points the spec already named:

- `rename` maps `Beneficiary / Originator` → `counterparty_name` and
  `IBAN / Account Number` → `counterparty_iban` (currently `beneficiary` and
  `iban`).
- `counterparty_name` comes out of the `drop(columns=[...])` list.
- `.astype({"counterparty_name": "string", "counterparty_iban": "string"})`
  alongside the existing `.astype({"amount": float})`.

**A correction to the spec, found in the code.** The spec says the importer
must "pass `iban` through instead of only validating it". The importer already
passes it through — `iban` is not in its drop list. It is `ImportStatement`
that validates and discards it. Only `beneficiary` is actually dropped by the
plugin. The fix is one drop-list entry and a rename, not two.

### 3.5 Reading the counterparty back

Issue 013 wants it visible on a read command without opening the database.
`entries-in-period` gets a `counterparty` column: `line.entry.counterparty_name
or "-"`. `query_lines_by_period_service` already does
`joinedload(JournalLine.entry)`, so the value is loaded before the session
closes and the detachment trap does not fire. One dict key in the CLI, no
service change, and it is the command a user is already in when they wonder
what a line was.

### 3.6 What must not change: the reference hash

```python
reference = sha256(f"{account.id}|{date}|{amount}|{description}")
```

Counterparty is **not** added. Issue 013 requires previously imported rows to
still be recognised as duplicates, and folding two new fields into the digest
would change every reference and silently re-import every statement the user
has ever imported. Written here because "the hash should cover everything we
know about the row" is a plausible-sounding improvement that would be a
disaster, and nothing in the code says otherwise.

---

## 4. Issue 014 — rules from the CLI

### 4.1 Model

```python
class Rule(base, Archivable):
    __tablename__ = "rules"

    id:         Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern:    Mapped[str] = mapped_column(String, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    priority:   Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    account: Mapped["Account"] = relationship("Account")
```

**No unique constraint.** Not on `pattern`, not on `(pattern, account_id)`.
Soft-deleted rules stay in the table (§4.3), so a retired rule would block
re-creating an identical one, and a duplicate rule is harmless anyway —
first-match-wins makes the second one dead weight, not a conflict.

### 4.2 Commands and use cases

```
kohle-cli add-rule PATTERN ACCOUNT [--priority N]
kohle-cli list-rules
kohle-cli remove-rule RULE_ID
```

`add_rule_cmd` → `add-rule`, `list_rules_cmd` → `list-rules`,
`remove_rule_cmd` → `remove-rule`, per the `_cmd`-stripping derivation the
existing design established.

`AddRule.execute(pattern, account_name, priority)` validates, in this order:

1. `pattern.strip()` non-empty → else `EmptyRulePattern`. An empty pattern
   compiles fine and matches everything, which is the one catch-all a user
   would never write on purpose.
2. `re.compile(pattern, re.IGNORECASE)` → `InvalidRulePattern(pattern, reason)`
   on `re.error`. This is issue 014's acceptance constraint, discharged here.
3. `get_account_by_name_service` → `AccountNotFoundError`, which already
   renders as `Account 'Grocerys' not found`. Issue 014's "clear error, not a
   traceback" needs no new work; the CLI's existing
   `raise click.ClickException(str(err))` shape does it.
4. `account_has_children_service` → `PostingToNonLeafAccount`. A rule pointing
   at a parent account can only ever produce entries `validate_lines` will
   reject, so rejecting it at creation converts a broken import into a
   refused rule.

**All four checks are in the use case, not the CLI**, following the precedent
the existing design set in §3: they are ledger rules, they need the database
for two of them, and a second frontend needs the same behaviour. The CLI's
share is `int` conversion of `--priority`, which Click does.

**No `AccountType` restriction on the target.** A rule routing a standing
order to a savings account is legitimate — imported lines are not all
expenses, and issue 017's phrase "a different expense or income account" is
describing the common case, not fixing the domain.

`list-rules` renders `id`, `priority`, `pattern`, `account` with `tabulate`,
ordered `priority ASC, id ASC`, live rules only. `No rules` on empty, matching
`list-accounts`' `No accounts`.

### 4.3 `remove-rule` is a soft delete, and this is not a stylistic choice

`remove_rule_service` sets `Rule.deleted_at = utcnow()` and is decorated
`@crud_delete`. `list_rules_service` and the matcher both filter
`deleted_at IS NULL`.

The forcing constraint is `Classification.matched_rule_id`. Three ways to
handle removing a rule that has already classified lines:

- **Hard `DELETE`.** `PRAGMA foreign_keys=ON` is set in
  `kohle/db/connection.py`, so SQLite refuses the delete outright while any
  classification references the rule. `remove-rule` would work only on rules
  that had never fired — that is, only on rules nobody needs to remove.
- **Hard `DELETE` with `ON DELETE SET NULL`.** Every classification the rule
  made silently becomes `matched_rule_id = NULL`, which is the encoding for
  "no rule matched this". It destroys the attribution the spec calls the
  reason `matched_rule_id` exists, and — because `NULL` is a meaningful value
  here and not a tombstone — it does it in a way no later reader can detect.
- **Soft delete.** The rule's row and, crucially, its *pattern text* survive,
  so a correction remains interpretable: *rule 7, pattern `(?i)amazon`, sent
  this to Books; a human moved it to Groceries.* That sentence is the training
  data. Chosen.

`Archivable.deleted_at` has existed on every table since the first migration
and nothing has ever written it. This is its first writer, which is the point:
the mechanism was already in the schema.

Not added: a `--all` flag on `list-rules` to show retired rules. The obvious
follow-up, no acceptance criterion asks for it, and the data is not lost.

---

## 5. Issue 015 — the import loop, and the operation-group seam

This is the delicate part, and the invariant it has to respect changed this
session.

### 5.1 What issue 011 actually established

`DbTransactionContext.record_transaction_step` creates the `OperationGroup`
lazily, on the first recorded write, and reuses `self.transaction_group` for
every write after it. A `DbTransactionContext` is constructed once per
`DbTransaction`, which is constructed once per `UnitOfWork._run`. Therefore:

> **One group per use-case invocation.** Not per entity, not per row.

`tests/test_operation_grouping.py` asserts exactly this — *"Two accounts, then
one entry: three writes, three groups"*, and *"The entry's group holds every
write the entry made — the EUR unit created on demand as well as the entry
itself."*

### 5.2 What that means for `ImportStatement`

One `ImportStatement.execute` is one `DbTransactionContext`, so **every write
in the whole import shares one group**: the on-demand `EUR` unit, both
unclassified bucket accounts, all N journal entries, and all N classification
rows. Issue 015's criterion — *"classification writes join the importing
entry's operation group rather than forming their own"* — is satisfied by
construction, and requires no new machinery whatsoever.

There is exactly one way to break it, and it is the shape a reader will reach
for first:

> **The classifier must be a `ctx`-taking function. It must never be a
> `UnitOfWork`.**

A `ClassifyEntry(UnitOfWork).execute(...)` called inside the per-row loop
would construct a second `DbTransaction` over some session. If it were handed
the outer session, `DbTransaction.execute` would **`commit()` and `close()`
that session in its `finally` on the first row**, and the remaining rows would
run against a closed session with the first half of the statement already
committed. If it were handed a fresh session, the classification rows would
commit independently of the entries they describe, in their own group,
defeating both this criterion and the transaction's atomicity. This is the
same structural reason the existing design (§5.2) gave for `RecordSimpleEntry`
being a *sibling* of `RecordJournalEntry` rather than a caller of it, and it
bites harder here because it is inside a loop.

So: `match_rule` is a pure function over already-loaded rules, and
`add_classification_service(ctx, ...)` is an ordinary `@crud_create` service.
Both take what they need and neither opens a transaction.

**Group granularity, flagged.** Issue 015 glosses its criterion as *"one
import row is one logical write"*, which reads as *group == row*. That is not
what the codebase does and not what issue 011 established: group == use-case
run, so a 40-row statement produces one group holding ~82 operations. Making
it per-row would mean adding a way to start a new group mid-transaction,
contradicting the invariant `AGENTS.md` records and re-introducing the
group-id fragmentation issue 011 removed. The criterion as written — writes
join the entry's group rather than forming their own — holds; its parenthetical
does not describe this system. Not changed.

### 5.3 The loop

Rules are loaded and compiled **once, before the loop.** N rows × M rules with
a query per row is the obvious mistake, and compiling a regex per row is the
less obvious one.

```
schema = {description, amount, date, counterparty_name, counterparty_iban}   # §3.3
validate_df_schema  → account → EUR unit → both unclassified buckets   (unchanged)

rules    = list_rules_service(ctx)      # ordered priority ASC, id ASC; live only
compiled = compile_rules(rules)         # pure; re.compile each pattern once

rows / reference hash / existing_references_service / new_rows            (unchanged)

for row in new_rows.to_dict("records"):
    amount       = Decimal(str(row["amount"]))
    magnitude    = abs(amount)
    counterparty = Counterparty(_optional_str(row["counterparty_name"]),
                                _optional_str(row["counterparty_iban"]))
    bucket_id    = expense_id if amount < 0 else income_id

    matched        = match_rule(compiled, row["description"], counterparty)
    counterpart_id = matched.account_id if matched else bucket_id

    lines = [ LineSpec(account.id,    unit_id, magnitude, 1, is_debit=amount > 0),
              LineSpec(counterpart_id, unit_id, magnitude, 1, is_debit=amount < 0) ]

    entry = post_entry(ctx, row["date"], row["reference"], row["description"],
                       lines, counterparty)                 ← was validate_lines + add_journal_entry_service

    add_classification_service(ctx,
        journal_entry_id    = entry.id,
        proposed_account_id = counterpart_id,
        matched_rule_id     = matched.rule_id if matched else None,
        final_account_id    = counterpart_id)
    imported += 1
```

Each step returns a `Result`; the first `Err` returns out of the closure and
`DbTransaction.execute` rolls the whole statement back. Nothing half-imports.

`entry.id` is available to the classification insert because `ctx.run` flushes
after every service op — the same fact `crud_create` already depends on to
populate `Operation.entity_id`.

**`post_entry` replaces the inlined pair.** The existing design (§5.2)
explicitly deferred this — *"a behaviour-neutral refactor of working, tested
code, and does not belong inside a feature slice"*. That deferral is now
spent: issue 015 requires the posting to route through `post_entry`, this
slice is rewriting the loop regardless, and `post_entry` is literally
`validate_lines` then `add_journal_entry_service` in that order, so the
substitution is exact.

**Landed in 013, not 015** (recorded during implementation). 013 is what adds
`post_entry`'s `counterparty` parameter, and the import loop is its only
caller that passes one — leaving the substitution to 015 would have shipped a
parameter with no call site for a slice. The substitution being exact is what
makes moving it harmless. 015 therefore inherits a loop that already posts
through `post_entry` and only adds the matcher and the classification insert.

**A matched rule whose account has since gained a child fails the whole
import**, with `PostingToNonLeafAccount` naming the account id. `AddRule`
already refuses non-leaf targets (§4.2), so this requires an `add-account
--parent <rule target>` after the fact. Failing loudly is chosen over falling
back to the bucket: a silent fallback means the user's rules stop working and
`list-unclassified` fills up with lines that *did* match, with nothing
anywhere saying why. The fix is one `remove-rule` away and the error names the
account.

**Import with an empty rule set is byte-for-byte the old behaviour on the
entry side.** `match_rule` returns `None` for every row, every row lands on
its bucket, the reference hash is unchanged, so re-importing a statement still
imports nothing. The only additions are the counterparty columns on the entry
and one classification row per new row.

`_optional_str(value) -> str | None` is a private helper in `journal.py`:
`None` for `pd.NA`/`NaN`/empty-or-whitespace, `str(value).strip()` otherwise.
Needed because `to_dict("records")` hands back `pd.NA` for missing string
cells (verified), which must not reach a `String` column, and because `''`
and `'   '` are the same fact as absent.

### 5.4 The matcher

In `kohle/use_cases/rules.py`, pure and unit-testable without a database —
the same treatment `_aggregate_by_unit` got, for the same reason:

```python
@dataclass(frozen=True, slots=True)
class CompiledRule:
    rule_id: int
    account_id: int
    pattern: re.Pattern[str]

def compile_rules(rules: Iterable[Rule]) -> list[CompiledRule]
def match_rule(compiled: Sequence[CompiledRule],
               description: str,
               counterparty: Counterparty) -> CompiledRule | None
```

`compile_rules` preserves the service's ordering and must not sort — the
ordering *is* the priority contract, and the same trap the ordered
average-cost fold carries. It is worth the same comment.

`match_rule` walks in order and returns on the first rule whose pattern
`.search()`es any of the three fields, skipping `None` fields.

`compile_rules` returns a plain list, not a `Result`. Every pattern in the
table compiled successfully when its rule was created, so a failure here means
the database was edited by hand — the same class of condition the existing
design (§6.2) declined to write a cycle-detection error for. If it happens
anyway, `re.error` propagates out of the use-case closure into
`DbTransaction.execute`'s broad `except Exception`, the transaction rolls
back, and the user gets the message. The seam `AGENTS.md` records an override
for is already the right handler.

---

## 6. Issue 016 — `list-unclassified`

### 6.1 The predicate, which the spec gets wrong

The spec offers two predicates as equivalent: `matched_rule_id IS NULL`, "or
equivalently, where `final_account_id` is still one of the unclassified
buckets". **They are not equivalent, and issue 016's own acceptance criteria
choose between them.**

Issue 016 requires: *"Lines corrected through 017 no longer appear, since they
are no longer unclassified."* A corrected fall-through line still has
`matched_rule_id IS NULL` — §2.2 and issue 017 both fix that the matched rule
is left as it was — so under the first predicate it would still appear, and
the criterion fails. Under the second, its `final_account_id` is now
`Groceries` and it drops out.

**Chosen: `final_account_id IN (unclassified bucket ids)`.** It also reads as
what the command means, and it does not need the `corrected` flag in the
predicate at all.

**This is why the interaction with issue 017 needs no code.** Issue 016 asks
the design to state the interaction if 017 has not landed. The answer: when
016 lands alone, nothing writes `corrected` or changes `final_account_id`, so
the predicate returns every unclassified line — correct. When 017 lands,
corrected lines disappear from the listing with **no change to 016's query**,
because 017 updates the column 016 filters on. The interaction is designed out
rather than sequenced.

### 6.2 Resolving the buckets without writing anything

The bucket ids come from `get_account_by_name_service` — the strict lookup —
**not** from `ImportStatement`'s `_get_or_create_account`. Using the
get-or-create helper would make a read-only command write two accounts and,
via `crud_create`, leave an `OperationGroup` behind, breaking issue 016's
"creates no operations of its own, and leaves no group behind".

An `AccountNotFoundError` for either bucket means nothing has ever been
imported, and the use case maps it to an **empty list**, not an error — issue
016's "nothing imported yet reports emptiness, not an error". This is the one
place in the slice where a domain error is deliberately swallowed, and it is
swallowed because the condition it reports is not an error at this call site.

### 6.3 Shape

```python
@dataclass(frozen=True, slots=True)
class UnclassifiedLine:
    entry_id:          int
    entry_date:        date
    description:       str
    counterparty_name: str | None
    counterparty_iban: str | None
    amount:            Decimal
    account_name:      str
```

Forced by the detachment trap the existing design documents in §6.3: the
session closes before the CLI reads the result, so nothing ORM-shaped may
cross the boundary. It carries exactly issue 016's required columns —
*"date, description, counterparty, amount, and the account the line landed
on"* — plus `entry_id`, which is `reclassify`'s handle (§2.4).

`unclassified_classifications_service` returns `Classification` rows with
`joinedload(Classification.final_account)` and
`selectinload(Classification.entry).selectinload(JournalEntry.lines)`.
`selectinload` for the collection, `joinedload` for the scalars: a
`joinedload` across a collection *and* a scalar produces a cartesian row
expansion that SQLAlchemy then de-duplicates, which is wasted I/O for no
benefit. Ordered `entry_date ASC, journal_entry_id ASC`.

`amount` is the value of the line on `final_account_id`. Both lines of an
import entry carry the same value by construction, so `lines[0].value` would
also work — picking the line by account is chosen because it stays correct if
an entry ever has more than two lines, and it costs one predicate.

`No unclassified lines` on empty output, matching the house style.

---

## 7. Issue 017 — `reclassify`

```
kohle-cli reclassify ENTRY_ID ACCOUNT
```

### 7.1 The adjusting entry, without branching on income vs expense

The naive implementation branches: for an expense, credit the wrong account
and debit the right one; for income, the reverse. That branch is unnecessary
and is the kind of thing that gets one case wrong. Instead, **mirror the
original counterpart line**:

```
original = the line of entry ENTRY_ID whose account_id == classification.proposed_account_id
wrong    = classification.final_account_id          ← current, not the original
right    = the named target account

lines = [ LineSpec(wrong, original.unit_id, original.quantity, original.unit_price,
                   is_debit = not original.is_debit),
          LineSpec(right, original.unit_id, original.quantity, original.unit_price,
                   is_debit = original.is_debit) ]

post_entry(ctx, original_entry.entry_date, uuid4().hex,
           f"Reclassify: {original_entry.description}", lines)
```

Walk both cases. An expense import debits `Unclassified Expense`; the
adjusting entry credits it and debits `Groceries`, so the bucket nets to zero
and `Groceries` holds the amount. An income import credits `Unclassified
Income`; the adjusting entry debits it and credits `Salary`. One expression,
both directions, and issue 017's last criterion — `balance` on the wrong
account no longer includes it, `balance` on the right one does — falls out.

Two details that are easy to get backwards:

- **The counterpart line is located by `proposed_account_id`, never by
  `final_account_id`.** After a first correction, the *original* entry still
  has its line on the proposed account; the final account's amount lives in
  the adjusting entry. `proposed_account_id` is the stable handle into the
  original entry.
- **The account being reversed out of is `final_account_id`, never
  `proposed_account_id`.** That is what makes a second correction (`A → B`
  then `B → C`) reverse out of `B` rather than out of the bucket a second
  time.

**The adjusting entry is dated the original entry's date, not today.**
`balance` and `entries-in-period` are period queries; dating the correction
today would leave last month's report permanently showing the expense in the
wrong account and this month's showing a phantom pair. When the correction was
*made* is not lost — `Archivable.created_at` on the new entry and the
`OperationGroup` both record it. The ledger's `entry_date` answers "when did
this economic event happen", and the event is the original purchase.

**Reference is `uuid4().hex`**, matching `record` and `record-split`, not a
content hash. Two corrections that happen to have identical content are two
facts, exactly as two identical `record` invocations are; a hash would make
the second one collide with `DuplicateJournalEntry`.

**Not checked: reclassifying a line to the account it is already on.** It
posts a self-cancelling two-line entry on one account. `validate_lines` passes
(it balances, the account is a leaf) and the unique constraint does not fire
(the sides differ). The existing design already ruled that shape valid-if-
pointless for `record 100 --from Cash --to Cash`; the same answer applies, and
adding a check here would be a rule that exists in one command and not its
sibling.

### 7.2 Updating the classification, and the update path that does not exist yet

`Classification.final_account_id` becomes the new account and `corrected`
becomes `True`. `proposed_account_id` and `matched_rule_id` are left exactly
as they were — issue 017 is explicit, and they are the record of what the
engine got wrong.

That is an **UPDATE**, and this codebase has no update path: `crud_create`
hardcodes `action="create"`, there is no `crud_update`, and nothing writes
`Operation.field` or `Operation.state`. Issue 017 leans on that absence to
justify the adjusting entry, and it is right about the *ledger*. But the
classification table is not the ledger — it is an annotation *about* the
ledger, and the spec and the issue both say in so many words that the row is
updated.

So `kohle/infrastructure/crud.py` gains the missing verbs:

```python
def _record_write(action: str):
    def decorator(fn):
        def wrapper(ctx, *args, **kwargs):
            result = fn(ctx, *args, **kwargs)
            if result.is_ok:
                entity = result.unwrap()
                ctx.record_transaction_step(Operation(
                    entity_type=entity.__tablename__, entity_id=entity.id, action=action))
                return Result.ok(entity)
            return Result.err(result.unwrap_err())
        return wrapper
    return decorator

crud_create = _record_write("create")
crud_update = _record_write("update")
crud_delete = _record_write("delete")
```

`crud_create`'s behaviour and every one of its call sites are unchanged; the
body moves into a factory because the three differ by one string and two
hand-copied audit blocks would drift. `crud_delete` exists rather than
labelling a soft delete as an update, because `list-operations` is the one
place in the system whose entire purpose is saying what happened.

**`Operation.field` and `Operation.state` stay unwritten.** Populating them
needs the service to report which fields changed and their before/after
values — a per-field audit model, which is a different feature. Half-building
it now yields two columns populated for one table and empty for every other,
and `list-operations` already omits them for exactly that reason.

`crud_update` gets two callers in this slice —
`set_classification_outcome_service` and, as `crud_delete`,
`remove_rule_service` — which is what makes it worth adding rather than
inlining once.

### 7.3 Rejected: an append-only classification log

Instead of updating, write a *second* `Classification` row for the correction
and read latest-wins. It has real appeal — it matches the ledger's own
append-only discipline and needs no `crud_update`.

Rejected on four counts. The `UniqueConstraint(journal_entry_id)` goes away,
so "the classification of this line" stops being a phrase with one referent.
Every read grows a max-per-entry subquery, including `list-unclassified`'s.
`proposed_account_id` and `matched_rule_id` must be copied forward onto the
correction row, duplicating the record of what the engine got wrong across N
rows and making "which rule was responsible" a question about which row you
happened to read. And it contradicts both the spec and issue 017, which say
the record is updated and the proposed account and matched rule are left as
they were. The append-only property that matters — that no posted entry is
ever edited — is preserved regardless, because the ledger is untouched.

### 7.4 Errors

`Reclassify.execute(entry_id, account_name)`:

- unknown or unclassified entry → `NoClassificationForEntry(entry_id)`
- unknown target account → `AccountNotFoundError`
- non-leaf target → `PostingToNonLeafAccount`, from the existing
  `validate_lines` inside `post_entry`, unchanged and not re-implemented

All three reach the user through the CLI's existing
`raise click.ClickException(str(err))`, which is issue 017's "clear error, not
a traceback" with no new CLI work.

---

## 8. Migrations and downgrades

**Three migrations, not one.** The spec says "(one Alembic migration)"; the
issue decomposition overrides it. 013, 014 and 015 are separately landable
vertical slices and each must be independently upgradable *and* downgradable,
which one combined migration makes impossible.

| slice | adds | downgrade |
|---|---|---|
| 013 | `journal_entries.counterparty_name`, `.counterparty_iban` | refuse if any row has either non-null; else drop both |
| 014 | `rules` | refuse if any row exists; else drop |
| 015 | `classifications` | refuse if any row exists; else drop |

013 and 014 are independent of each other, so whichever lands second sets its
`down_revision` to the first. The chain stays linear — **do not create an
Alembic branch**; two heads over a single-user SQLite file buys nothing and
costs a merge revision. 015 must follow 014, which its dependency order
already guarantees, because `classifications.matched_rule_id` has a foreign
key to `rules.id`.

**The refusal standard, per issue 012.** Each `downgrade()` opens with a
`_refuse_if_unrepresentable()` modelled on
`7f3c1d9a2b40_multi_unit_ledger.py`: count what would be destroyed, and if
anything would be, `raise RuntimeError` naming the counts and telling the user
to back up `kohle.db` and export first. The counting happens **before any
schema statement**, so a refusal leaves the database exactly as it was —
which is what `tests/test_migration_downgrade.py` asserts with
`assert "journal_lines" in _tables(db), "refusal must leave the schema
untouched"`.

For 013 specifically:

```sql
SELECT COUNT(*) FROM journal_entries
 WHERE counterparty_name IS NOT NULL OR counterparty_iban IS NOT NULL
```

Non-zero → refuse, naming the count. Zero → drop both columns cleanly, which
is issue 013's "either the columns are dropped cleanly, or the downgrade
refuses and names what would be lost", with both branches live rather than
one.

**`op.drop_column` works directly on SQLite here — verified**, Alembic 1.18.3
against SQLite 3.45.1 in this venv, no `batch_alter_table` required. Worth
recording because the folklore is that SQLite cannot drop columns; that
stopped being true in SQLite 3.35, and the batch-mode table rebuild the
existing migration uses for `accounts` was needed for a *different* reason
(relaxing NOT NULL and adding a self-referential FK), not for dropping.

For 014 and 015 the refusal is `SELECT COUNT(*)` on the table itself.
Dropping a populated `rules` table loses the user's rule set; dropping a
populated `classifications` table loses the training data the entire spec
exists to accumulate. Both refuse. In practice these downgrades will almost
always refuse, and that is the honest outcome — the same one the multi-unit
migration reaches for any ledger with entries in it.

Each migration gets tests in `tests/test_migration_downgrade.py`, in the
established shape: upgrade to head, seed through raw `sqlite3`, downgrade,
assert either the round trip or the `RuntimeError` and an untouched schema.

---

## 9. The decision categories

### State and data lifecycle

**One import is one transaction, and that is now load-bearing in a way it was
not before.** `ImportStatement` writes, per row, a `JournalEntry` with two
`JournalLine`s and one `Classification` — three tables that must agree. A
partial commit would leave entries with no classification (invisible to
`list-unclassified`, so a permanently lost line) or classifications pointing
at entries that do not exist. `DbTransaction.execute` commits once, at the
end, after the loop; any `Err` from any row returns out of the closure and
rolls the whole statement back. §5.2 spells out the one construct that would
break this.

Partial completion is therefore not observable anywhere in this slice. The
same holds for `reclassify`, whose adjusting entry and classification update
are two writes in one transaction: an entry posted without the record being
updated would make the line show up in `list-unclassified` forever despite
having been corrected.

**Reversibility.** The ledger stays strictly append-only: no entry is edited,
voided or deleted by anything in this slice. `reclassify` posts. The
*annotation* layer is mutable in exactly two controlled places —
`classifications.final_account_id`/`corrected` and `rules.deleted_at` — and
both are audited through `crud_update`/`crud_delete`, so `list-operations`
shows the change even though the before-value is not stored (§7.2). Neither
mutation loses information: the correction's prior state is reconstructible
from the entries themselves, and a retired rule keeps its pattern.

**Replayability.** Re-importing a statement remains a no-op, guaranteed by the
unchanged reference hash (§3.6) and by `UniqueConstraint(journal_entry_id)` on
`classifications`, which makes a duplicate classification structurally
impossible even if duplicate detection were bypassed. `reclassify`, like
`record`, is deliberately *not* idempotent: running it twice posts two
adjusting entries, the second one cancelling the first if the target is the
same. That is the same trade the existing design took for hand entry.

**Auditability** is the point of the whole slice. Every write goes through a
`crud_*` decorator, so rules, classifications, corrections and adjusting
entries all appear in `list-operations`, in one group per command.

### Error propagation

Unchanged in structure; the existing three representations and two conversion
seams hold. What this slice adds at each layer:

1. **Infrastructure** — untouched. `DbTransactionContext.run` still converts
   arbitrary failure into `UniqueViolation` / `InfrastructureError`; it is now
   also the net that catches a hand-corrupted regex pattern (§5.4). The
   `BLE001` override in `AGENTS.md` continues to apply here and nowhere else.
2. **Services** — `rule_services` and `classification_services` map
   `UniqueViolation` to named domain errors and everything else to their
   family's base. No new constraint needs a named mapping: `rules` has no
   unique constraint (§4.1), and a `classifications.journal_entry_id`
   violation is unreachable through the use cases.
3. **Use cases** — new domain errors and three union aliases in
   `domain_errors.py`, in the existing style:
   ```
   RuleError(Exception)
     EmptyRulePattern, InvalidRulePattern(pattern, reason), RuleNotFoundError(rule_id)
   ClassificationError(Exception)
     NoClassificationForEntry(entry_id)

   AddRuleError     = AccountError | RuleError | JournalError
   ReclassifyError  = AccountError | JournalError | ClassificationError
   ImportStatementError += RuleError | ClassificationError
   ```
   `PostingToNonLeafAccount` is reused for a non-leaf rule target rather than
   given a rule-specific twin: it is the same rule, checked earlier.
4. **CLI** — still never inspects an error type; still prints `str(err)`.
   Every new error defines `__str__`, which is what makes issues 014's and
   017's "clear error, not a traceback" criteria fall out.

The one place a layer deliberately *drops* information is
`ListUnclassified` swallowing `AccountNotFoundError` for a missing bucket
(§6.2), because at that call site the condition is emptiness, not failure.

`DataframeMissingColumn` and `DataframeColumnTypeMismatch` gain `__str__`
(§3.3) — the plugin contract's enforcement is a message, so the message is
part of the contract.

### Concurrency and ownership

**Single threaded, no shared mutable state, no concurrency of any kind.**
Stated rather than assumed, and it matters more here than in the previous
slice because this one adds a loop that accumulates.

Everything the new code owns is either a local or a frozen value.
`compile_rules` returns a fresh `list[CompiledRule]` per import; `CompiledRule`
is frozen and `re.Pattern` is itself thread-safe and immutable, so nothing
would break if it were shared — but it is not shared, and it must not be
cached across imports at module level, because a rule added between two
imports has to take effect. The `imported` counter is a local in the closure.
`DbTransactionContext.transaction_steps` remains a plain unsynchronised list,
now longer per import than before.

The `Session` is owned by `DbTransaction` and closed by it. The whole of §5.2
is a statement about ownership: the classifier borrows the caller's `ctx` and
must never take ownership of a session.

SQLite's single-writer file lock is unchanged; a concurrent TUI would get
"database is locked". Not addressed, not made worse — though an import is now
a longer transaction than it was, so the window is wider.

### Reuse

Used rather than reimplemented:

- **`post_entry`** for every entry this slice posts, both the classified
  import line and the `reclassify` adjusting entry — which is the existing
  design's stated intent for it, discharged.
- **`validate_lines`** through `post_entry`, unmodified: balance-by-value and
  leaf-only posting are not re-implemented anywhere in this slice, and the
  non-leaf rule target check in `AddRule` reuses
  `account_has_children_service` rather than duplicating the predicate.
- **`crud_create`** and the whole `UnitOfWork` / `DbTransactionContext`
  machinery for every new write.
- **`Archivable.deleted_at`**, already on `rules` by inheritance, for
  retirement (§4.3) — a mechanism that has been in the schema since the first
  migration with no writer.
- **`get_account_by_name_service`**, **`account_has_children_service`**,
  **`existing_references_service`**, **`_get_or_create_account`** — all
  existing, all unchanged.
- **`validate_df_schema`** for the extended plugin contract: the enforcement
  mechanism for the new columns already exists and needs two dict entries.
- **`tabulate`**, `click.echo`, the `_cmd` naming derivation, the
  `No <things>` empty-output convention, `DecimalParamType` — house style.
- **`_refuse_if_unrepresentable`**'s shape from the multi-unit migration, and
  the `tests/test_migration_downgrade.py` fixture, for all three migrations.

Introduced here and worth reusing next:

- **`Counterparty`** — the pair every future importer-adjacent feature will
  carry, and the input any future matcher (including an ML one) consumes.
- **`match_rule` / `CompiledRule`** — the pure, DB-free classification
  decision. An ML classifier is a second implementation of the same
  *signature*, which is the cheapest possible seam for the deferred phase.
- **`crud_update` / `crud_delete`** — the two missing verbs. Any future
  correction or retirement uses them instead of inventing a third path.
- **`Classification`** — the labelled dataset. Nothing else needs to
  accumulate it.

### Extension points

- **`Classification` is the extension point for the ML phase**, and it is the
  only one this slice exists to create. Contract: one row per classified
  entry, `proposed_account_id` and `matched_rule_id` frozen at the moment of
  the decision, `final_account_id` and `corrected` reflecting the human
  verdict. A model trains on `(entry.description, entry.counterparty_name,
  entry.counterparty_iban) → final_account_id`, weighted by `corrected`. That
  contract is what must not be broken by later changes — specifically, the
  append-only-per-entry rule for the two frozen columns (§7.3) and the soft
  delete of rules (§4.3), which together keep every historical decision
  interpretable.
- **`match_rule`'s signature** is the seam a scored or learned classifier
  slots into. Nothing is abstracted for it now (see below); the signature
  being pure and DB-free is the whole affordance.
- **The importer plugin contract** gains two required columns. That is a
  breaking change to a published extension point with one in-repo
  implementation, and it is versioned by nothing — a third-party plugin
  fails at `validate_df_schema` with the missing column named, which is the
  intended and only failure mode (§3.3).
- **`post_entry`** continues as the extension point for new ways of making
  entries; `Reclassify` is its third caller and adds nothing to it but an
  optional parameter.

**No plugin surface is added for rules.** The `kohle.plugins` entry-point group
is for statement importers and, later, price fetchers. A pluggable classifier
is the ML phase's problem, and it would be a plugin seat with zero occupants.

**No abstraction for the future ML classifier.** No `Classifier` protocol, no
strategy object, no registry. There is one implementation, the second one does
not exist and is explicitly out of scope, and inventing the interface now
means guessing at what a model needs from a use case — which is exactly the
guess the spec defers by requiring labelled data first.

### Build vs. buy

- **Pattern matching — buy**, stdlib `re`. Evaluated and rejected: a
  hand-written substring matcher (too weak, §2.1), a `pyparsing` DSL
  (`pyparsing` is already a dependency, so the cost is real work rather than a
  new package — rejected on the grammar/evaluator/docs cost against no
  capability regex lacks here, §2.1), and the `regex` PyPI package (its one
  advantage over stdlib `re` is a match timeout, which buys ReDoS protection
  against patterns the user writes for themselves — a new dependency for a
  self-inflicted, Ctrl-C-recoverable failure).
- **Rule storage — buy nothing, build nothing.** A `rules` table through the
  existing `crud_create`/`UnitOfWork` machinery. The spec's alternative — a
  config file — was settled during the interview; recorded here only because a
  YAML rule file is what most ledger tools do, and the reason not to is that
  every other first-class entity in this codebase is a DB row with CLI CRUD,
  and a file would need its own parser, its own validation timing (which is
  where issue 014's creation-time-rejection criterion would become
  unsatisfiable), and its own story for how `matched_rule_id` refers to a rule
  that has since been edited in place.
- **The classification/audit update path — build**, `crud_update` and
  `crud_delete`, twelve lines total including the shared factory (§7.2).
  Evaluated: `sqlalchemy-continuum` and similar versioning extensions give a
  full temporal history with before-values, which is strictly more than
  needed, adds a dependency, adds shadow tables to every model, and would sit
  awkwardly beside the hand-rolled `Operation` trail that already exists.
- **Regex validation at rule-creation — buy**, `re.compile` and `re.error`.
  There is no hand-written check to consider.
- **Table rendering, decimal parsing, CLI plumbing — buy**, unchanged:
  `tabulate`, `DecimalParamType`, Click.
- **Fuzzy / scored matching — neither.** Out of scope by the spec's
  Non-Goals; `rapidfuzz` is the obvious purchase when it is in scope, and it
  is named here so the evaluation is not redone from scratch.

### Abstractions introduced

Each with the problem that forces it. Anything without one is not here.

| Abstraction | Forcing problem |
|---|---|
| `Counterparty` | The pair crosses four signatures, and as loose parameters the matcher takes three adjacent `str \| None` arguments where transposing two of them type-checks and silently matches the wrong patterns against the wrong fields (§3.2). |
| `CompiledRule` | `re.compile` must happen once per import, not once per row; the compiled pattern has to travel with the `rule_id` and `account_id` it belongs to, and an ORM `Rule` cannot carry a `re.Pattern`. |
| `match_rule` (as a pure function) | Makes the classification decision testable without a database and keeps it out of the transaction, which is what stops it from being written as a `UnitOfWork` (§5.2). |
| `UnclassifiedLine` | The session closes before the CLI reads the result; nothing ORM-shaped may cross that boundary (the existing design's §6.3 trap). |
| `Classification` | The spec's central requirement; the labelled record cannot be derived from the ledger afterwards, which is what "expensive to retrofit" means. |
| `crud_update` / `crud_delete` | The classification outcome and the rule retirement are mutations, and there is no audited mutation path in the codebase at all (§7.2). |
| `_record_write(action)` | Three decorators differing by one string; two hand-copied audit blocks drift. Deduplication, not indirection — `crud_create`'s behaviour and call sites are unchanged. |
| `_optional_str` | `to_dict("records")` yields `pd.NA` for missing string cells, which must not reach a `String` column, and `''`/`'   '` must collapse to the same `NULL` (§5.3). |

Explicitly **not** introduced, having no forcing problem:

- A `Classifier` / `MatchStrategy` protocol. One implementation; the second is
  a different spec.
- A `field` enum on `Rule` (§2.1) and a `RuleSet` wrapper around
  `list[CompiledRule]` — the list is the rule set.
- A `Counterparty` *table* or FK. Counterparties are strings a bank sent.
- A `Correction` entity separate from `Classification`. The correction is two
  columns on the row it corrects.
- A repository layer, a `ClassificationRepository`, or any generic CRUD base.
  The services are that layer.
- An `ImportSummary` return type for `ImportStatement` (see below).

### Alternatives rejected

Consolidated; each is argued where it arises.

| Rejected | Where | Short reason |
|---|---|---|
| Substring patterns | §2.1 | satisfies the creation-time-rejection criterion only vacuously; cannot anchor or alternate |
| A small pattern DSL | §2.1 | grammar + evaluator + docs for no capability regex lacks here |
| A `field` selector column on `Rule` | §2.1 | per-field `.search()` already gives the wanted behaviour; the case it prevents is not a failure |
| Normalizing whitespace before matching | §2.1 | the printed description would stop being the matched description |
| Matching against a concatenated haystack | §2.1 | `^`/`$` would anchor the blob, making exact-IBAN rules inexpressible |
| Most-specific-wins (longest pattern) | §2.3 | length is not specificity for regexes; `.*` is short and matches everything |
| Refusing the import when two rules match | §2.3 | turns a resolvable ambiguity into a failed statement import |
| A unique constraint on `priority` | §2.3 | forces renumbering to insert; `id` as tie-break already gives a total order |
| Identifying a line by entry `reference` | §2.4 | a 64-char sha256 nobody will retype |
| Identifying a line by classification id | §2.4 | a second small-integer id space that silently resolves to the wrong row |
| Adding counterparty to the reference hash | §3.6 | would re-import every previously imported statement |
| A placeholder value for a missing counterparty | §3.1 | a placeholder is a string a rule can match by accident; `NULL` is not |
| Treating a missing plugin column as all-null | §3.3 | exactly the silent omission the spec forbids; a rule stops matching with nothing saying why |
| Hard `DELETE` for `remove-rule` | §4.3 | `PRAGMA foreign_keys=ON` refuses it for any rule that ever fired |
| `ON DELETE SET NULL` on `matched_rule_id` | §4.3 | silently rewrites "rule 7 did this" to "no rule did this", undetectably |
| A `ClassifyEntry(UnitOfWork)` called per row | §5.2 | commits and closes the session on the first row, mid-import |
| A new `OperationGroup` per import row | §5.2 | contradicts the invariant issue 011 established and `AGENTS.md` records |
| Falling back to the bucket when a rule's account is non-leaf | §5.3 | silently disables the user's rules and fills `list-unclassified` with lines that did match |
| Loading or compiling rules inside the row loop | §5.3 | N×M queries and N regex compilations for a fixed rule set |
| `matched_rule_id IS NULL` as `list-unclassified`'s predicate | §6.1 | corrected fall-through lines would never leave the list, failing issue 016 |
| `_get_or_create_account` for the buckets in `list-unclassified` | §6.2 | a read-only command would write two accounts and leave a group |
| Branching on income vs expense in `reclassify` | §7.1 | mirroring the original line's side handles both with one expression |
| Dating the adjusting entry today | §7.1 | leaves the original period permanently misreported |
| A content hash as the adjusting entry's reference | §7.1 | two identical corrections are two facts; a hash makes the second collide |
| An append-only `Classification` log instead of an update | §7.3 | loses the one-row-per-entry referent, needs max-per-entry subqueries, duplicates the frozen columns, and contradicts issue 017 |
| Writing `Operation.field` / `.state` for updates | §7.2 | needs a per-field before/after model; half-building it populates two columns for one table |
| One combined migration for all three slices | §8 | the slices land independently and each must downgrade independently |
| An Alembic branch for the independent 013/014 | §8 | two heads and a merge revision over a single-user SQLite file |
| `batch_alter_table` to drop the counterparty columns | §8 | unnecessary since SQLite 3.35; `op.drop_column` verified working here |
| An `ImportSummary` return type (`imported` / `classified` / `unclassified`) | below | a second way to learn what `list-unclassified` says |

On that last one: making `ImportStatement` return a summary instead of an
`int` is genuinely tempting — "12 imported, 8 classified, 4 need a rule" is a
better message than "12 entries imported". It is not done because no
acceptance criterion asks for it, it changes a return type three tests and one
CLI command depend on, and `list-unclassified` — which this slice is building
anyway, one command later — answers the same question with more detail. If it
is wanted, it is a small follow-up and this is the note saying so.

---

## 10. Issue mapping

| Issue | Lands |
|---|---|
| 013 counterparty on imported entries | `JournalEntry` columns + migration (§3.1, §8); `Counterparty` (§3.2); extended plugin contract and its dtype clause (§3.3); DB importer fix (§3.4); `entries-in-period` column (§3.5); `post_entry` gains the parameter, and the import loop routes through it (§5.3); `_optional_str` |
| 014 rules from the CLI | `Rule` + migration (§4.1, §8); `rule_services.py`; `AddRule`/`ListRules`/`RemoveRule` (§4.2); regex validation at creation (§2.1); ordering (§2.3); soft delete + `crud_delete` (§4.3, §7.2) |
| 015 classify and record | `Classification` + migration (§2.2, §8); `classification_services.py`; the matcher (§5.4); the matching and classification insert in the `ImportStatement` loop (§5.3); the group seam (§5.1–5.2) |
| 016 list unclassified | `unclassified_classifications_service`; `UnclassifiedLine` + `ListUnclassified` (§6.3); the `final_account_id` predicate (§6.1); strict bucket lookup (§6.2) |
| 017 reclassify | `Reclassify` (§7.1); `set_classification_outcome_service` + `crud_update` (§7.2); `NoClassificationForEntry` |

Dependency order is the issue order: 013 and 014 are independent of each other
and both precede 015; 016 and 017 both depend on 015 and are independent of
each other. 013 before 015 because the matcher has nothing to match on
otherwise; 014 before 015 because `Classification.matched_rule_id` needs
`rules` to exist.

---

## 11. Testing notes

Extends the existing four-layer pattern — pure functions with no fixture,
services and use cases against the `session`/`session_factory` fixtures, CLI
through `CliRunner` with an injected factory.

**Pure, no database.** `match_rule` gets the bulk of the unit tests, because
it is where every decision in §2.1 and §2.3 lives and none of them needs a
session: first-match-wins across a priority-ordered list; the tie-break falling
to `id`; a pattern matching on description but not counterparty and vice
versa; an anchored IBAN pattern matching the IBAN field exactly and not
matching a description that merely contains it; case-insensitivity and the
`(?-i:...)` escape; `None` fields skipped rather than crashing; an empty rule
list returning `None`. `_optional_str` gets `pd.NA`, `NaN`, `''`, `'  '` and a
normal string.

**Regression guards for the traps this design names.** Each of these exists
because the code is correct in a way that is easy to silently break later:

- `compile_rules` preserves the service's ordering — the same class of guard
  as the ordered average-cost fold.
- An import of a statement whose counterparty column is empty on *every* row
  succeeds. This is the `float64` dtype trap from §3.3 and it is the one test
  that would have caught the latent bug in the current `iban` column.
- The reference hash is unchanged: import a statement, add counterparty data,
  re-import, assert zero new entries (§3.6).
- One import produces **one** `OperationGroup` holding every entry and every
  classification — the direct extension of
  `test_write_creates_exactly_one_group_holding_its_operations`, and the guard
  against someone converting the classifier into a `UnitOfWork` (§5.2).
- A failing row mid-import leaves no entries, no classifications and no group
  — atomicity, asserted rather than assumed.
- `list-unclassified` after a `reclassify` no longer shows the line, with no
  change to the query (§6.1).

**Use-case level.** `AddRule` rejecting a malformed pattern *at creation*, with
the message naming the position — issue 014's acceptance criterion is a test,
not a prose claim. `AddRule` rejecting an unknown account and a non-leaf
account. `RemoveRule` retiring a rule that has already classified lines, and
those classifications still resolving their `matched_rule` afterwards (§4.3).
A double `reclassify` (`bucket → A → B`) landing the amount on `B` with `A` and
the bucket both at zero, which is the §7.1 detail about reversing out of
`final_account_id` rather than `proposed_account_id`.

**Migrations.** Three additions to `tests/test_migration_downgrade.py`, in the
established shape: for each migration, a clean round trip on empty data and a
refusal on populated data that asserts the schema is untouched.

**CLI.** `add-rule` with a malformed pattern exits non-zero with the regex
message and no traceback; `list-rules` renders in evaluation order with the id
column `remove-rule` needs; `list-unclassified` on an empty ledger prints the
empty message rather than failing; `reclassify` on an unknown entry id prints
`NoClassificationForEntry`.

---

## 12. What the spec and the issues got wrong

Recorded because the design deviates from them and a later reader needs to
know it was deliberate.

1. **"or equivalently" in the spec's `list-unclassified` paragraph is false.**
   `matched_rule_id IS NULL` and `final_account_id IN (buckets)` diverge for
   corrected fall-through rows, and issue 016's last criterion rules out the
   first. §6.1.
2. **The Deutsche Bank importer does not drop `iban`.** The spec says it must
   be "passed through instead of only validating it"; the plugin already
   passes it through, and it is `ImportStatement` that discards it. Only
   `beneficiary` is dropped by the plugin. §3.4.
3. **"one Alembic migration" does not survive the slice decomposition.**
   Three, one per schema-bearing issue, so each lands and downgrades on its
   own. §8.
4. **Issue 015's "one import row is one logical write" does not describe this
   system.** Groups are per use-case run, per issue 011 and per `AGENTS.md`.
   The criterion it justifies still holds. §5.2.
5. **Issue 017's "there is no update path" is true of the codebase and is
   about to become less true.** It correctly forces the adjusting entry for
   the *ledger*; the classification row it also requires to be updated needs
   `crud_update`, which this slice adds. §7.2.
6. **A latent bug the slice inherits:** an all-empty text column from
   `read_csv` is `float64`, so today's `iban` schema check already fails on a
   statement with no counterparty IBANs anywhere. Fixed by the dtype clause in
   the contract. §3.3.
7. **Stale comment in `list_operations_cmd`** — "until issue 011 lands", which
   it has. Deleted as part of this slice's CLI work.
