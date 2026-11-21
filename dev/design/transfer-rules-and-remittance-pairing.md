# Design: Transfer rules and remittance pairing

Spec: `dev/specs/transfer-rules-and-remittance-pairing.md` (frozen).
Issues: `dev/issues/126`–`136`.

Precedents, cited by short name:

- **EC**: `dev/design/expense-classification.md`
- **CC**: `dev/design/complex-classification-rules.md`
- **MC**: `dev/design/multi-currency-and-fx.md`

Layering per `AGENTS.md` stays `app -> use_cases -> services ->
infrastructure/domain`. Only services touch a `Session`. Functions return
`Result[T, E]`; domain errors are `Exception` subclasses used as values.

**Upstream state this design assumes.**

- The spec is in `dev/specs/`, so it is treated as frozen. It and the issues
  are untracked in git, and the inbox copy shows as deleted; the move is not
  committed yet.
- Every Requirements item marked "recommended default, not yet confirmed" is
  taken as written, except where §17 says it cannot be built as written. Those
  points, and the places where the design had to choose behaviour the spec
  leaves open, are collected in §17 for the user to confirm or overrule. The
  four that most need an answer are §17 items 1 to 4.
- Changes to issue scope and order are in §16.

---

## 1. Summary of the shape

| Concern | Decision | § |
|---|---|---|
| Rule-file keys | One action key per rule: `account = "Groceries"` (today), `transfer = "Savings"`, or `remittance = "IndianBank"` with `unit = "INR"`. | 3.1 |
| Rule storage | `rules.kind` (`category` / `transfer` / `remittance`) and `rules.unit_id`, immutable like `account_id`. Content identity is `(when, kind, account, unit)`. | 3.2 |
| "Counterpart is the importing account" | Cannot be checked when the file is applied, because rules are not per account. A transfer or remittance rule instead never matches a row imported into its own counterpart; evaluation moves on to the next rule. | 3.4, 17.1 |
| Classification record | `classifications.kind` (`category` / `transfer` / `mirror` / `remittance`), `mirror_of_entry_id`, `remittance_account_id`, `remittance_unit_id`, `completion_entry_id`, with CHECKs tying each column to its kind. The direction is read from the line's sign, not stored. | 4 |
| An absorbed row | Posted as its own fall-through, then moved onto its own account by an adjusting entry, in the same transaction. That is the same shape as a later join, so every correction reuses `post_correction`. | 5.4 |
| Where the mirror lookup runs | Inside the import's own transaction, before `match_rule`. Open transfers into the importing account are loaded once per statement; a pure function picks the nearest. `match_rule` gains only a pure parameter. | 5.3 |
| Module layout | New `transfers.py` and `remittances.py`. `post_entry`, `validate_lines`, `post_correction`, `Total` and `_cross_unit_lines` move down into a new `posting.py`, and the bucket names into `accounts.py`, so that `journal.py` can call the transfer code without a cycle. Every old import path keeps working through re-exports. | 2 |
| Pending bucket | `Pending Remittances`, an asset account, created on first use by a remittance. It is never created by a ledger without remittance rules. | 9.1 |
| Pending listing | Its own command, `list-pending-remittances`, not `list-unclassified`. | 9.3 |
| Commands | `list-unmirrored-transfers`, `join-transfer LINE_ENTRY TRANSFER_ENTRY`, `unjoin-transfer LINE_ENTRY`, `list-pending-remittances`, `complete-remittance ENTRY_ID AMOUNT`, `uncomplete-remittance ENTRY_ID`. | 10 |
| Completion | The two-amount form of MC issue 111 (outgoing) or 115 (incoming), built by the existing `_cross_unit_lines`, dated at the original line. A completion that consumes lots replays the currency lots before committing and refuses a shortfall. | 9.4 |
| Wrong Y | A reversal entry carries `journal_entries.reverses_entry_id`. The lot replay treats an entry and its reversal as if neither existed, which restores the lots and un-realises the gain exactly. | 9.5, 17.4 |
| Migrations | Three: transfer columns (126), remittance columns (132), `reverses_entry_id` (135). | 12 |
| Slice order | Unchanged, 126 → 136. Some criteria move between issues (§16). | 16 |

**New files**

| File | Contents | Slice |
|---|---|---|
| `kohle/use_cases/posting.py` | `validate_lines`, `post_entry`, `post_correction`, `Total`, `_cross_unit_lines`, the classified-line helpers; later `post_reversal` | 127 (moves), 135 |
| `kohle/use_cases/transfers.py` | The pure mirror matcher, `absorb`/`unabsorb`, the transfer path, `ListUnmirroredTransfers`, `JoinTransfer`, `UnjoinTransfer` | 127–131 |
| `kohle/use_cases/remittances.py` | `complete_remittance`, `uncomplete_remittance`, `ListPendingRemittances`, `CompleteRemittance`, `UncompleteRemittance` | 132–135 |
| three migrations | §12 | 126, 132, 135 |
| `docs/examples/transfers.csv`, `docs/examples/savings.csv` | Fictional June statements for Checking and Savings | 127, 132 |

**Changed:** `kohle/domain/models.py`, `kohle/domain/domain_errors.py`,
`kohle/use_cases/accounts.py`, `journal.py`, `rules.py`, `classification.py`,
`splitting.py`, `lots.py`, `kohle/services/classification_services.py`,
`journal_services.py`, `rule_services.py`, `kohle/db/schema.py`
(`HEAD_REVISION`), `kohle/app/cli/cli.py`, `docs/import-and-classification.md`,
`docs/recording-entries.md`, and the tests named in §18.

**The existing patterns this follows.**

- **One move primitive.** CC §7.4 made `_post_correction` "the one place a line
  moves between accounts after import". Transfers, mirror absorption,
  un-absorption and joins are all moves of a classified line, so all of them
  go through it (§5.4).
- **The record is updated, the ledger is appended to** (EC §7.2, §7.3).
  Classification rows are updated through `crud_update`; every ledger change
  is an adjusting entry dated at the original line.
- **A link to the current effecting entry, set to NULL on undo.** `Split` has
  `adjusting_entry_id`, NULL after `unsplit-line`. The remittance's
  `completion_entry_id` works the same way (§9.5).
- **Plan, then apply with a re-plan.** `classify-rules` keeps its two
  transactions and its `ClassifyPlanChanged` guard (CC §7.5).
- **Names moved down, re-exported from the old module.** MC §2.7 moved
  `balance_sheet_accounts` and `BASE_CURRENCY` to break the `journal ↔ lots`
  cycle. §2 does the same for posting.
- **Lazily created well-known accounts** (EC §6.2): the unclassified buckets
  on import, the pending bucket on the first remittance.
- **The no-regression oracle captured from pre-feature code** (MC §12.1,
  issue 124).

---

## 2. Module layout and the moves

### 2.1 The cycle that forces it

`ImportStatement` lives in `journal.py`. At import it must:

- absorb a mirror, which posts an adjusting entry; and
- after a transfer rule fires, absorb the counterpart's fall-through.

Both are transfer logic, and both post. If that logic lives in `transfers.py`
and `transfers.py` imports `post_entry` from `journal.py`, then `journal.py`
cannot import `transfers.py`. Putting it all inside `journal.py` instead would
split one concept over three modules: the pure matcher, the import half in
`journal.py`, and the corrections in `classification.py`.

`remittances.py` has the same constraint for a future reason. The spec says
completion must be callable by a later Indian bank importer, whose rows will
go through `ImportStatement`. So `journal.py` must one day be able to import
`remittances.py`, and `remittances.py` must not import `journal.py`.

### 2.2 What moves

| Name | From | To | Re-exported from |
|---|---|---|---|
| `validate_lines`, `_validate_price_currencies`, `post_entry` | `journal.py` | `posting.py` | `journal.py` |
| `_PRICE_SCALE`, `Total`, `_cross_unit_lines` | `journal.py` | `posting.py` | `journal.py` (`test_cross_unit_lines.py` imports `_cross_unit_lines` from there) |
| `_post_correction` | `classification.py` | `posting.py`, as `post_correction` | nothing; no test names it |
| `_rule_amount` | `classification.py` | `posting.py`, as `statement_amount` | nothing |
| `UNCLASSIFIED_EXPENSE`, `UNCLASSIFIED_INCOME` | `journal.py` | `accounts.py`, beside `PEOPLE_ROOT` | `journal.py` (`test_classification.py` imports them there) |
| `_get_or_create_account` | `journal.py` | `accounts.py`, as `get_or_create_account` | nothing |

- **Re-exports** are written `from x import NAME as NAME`, as MC §2.7 did, so
  ruff reads them as intentional.
- **The moves are behaviour-neutral** and land as the first commit of 127,
  before any transfer code, so the diff of the move is reviewable on its own.

`posting.py` also gains three helpers, which name the anatomy of an imported
entry that `post_correction`, `_to_unclassified_line` and `_rule_amount`
already rely on:

```python
def counterpart_line(classification: Classification) -> JournalLine
    # the line on proposed_account_id: where the import put the other side
def statement_line(classification: Classification) -> JournalLine
    # the other line: the row's own account. For the old self-targeted
    # category rule (both lines on one account) it is that account.
def statement_amount(classification: Classification) -> Decimal
    # signed, as on the statement: -value when the counterpart line is a debit
```

### 2.3 Import direction after the change

```
cli ──► classification ──► journal ──► transfers ──► posting ──► services
 │            │  └────────► rules     │              accounts ──► services
 │            └──► transfers          └──► lots ───► accounts
 ├──► remittances ──► posting, lots, accounts
 └──► splitting ──► journal
```

- `posting.py` imports only services and models.
- `transfers.py` imports `posting`, `accounts`, `conditions` (for
  `normalise_iban`) and services. It never imports `journal`,
  `classification` or `rules`.
- `remittances.py` imports `posting`, `lots`, `accounts`, `conditions` (for
  `Direction`) and services. It never imports `journal`.
- `journal.py` still never imports `classification.py` (EC §1).
- `tests/test_price_guards.py` gains `posting.py`, `transfers.py` and
  `remittances.py` in `_guarded_sources` and `RECORDING_MODULES`.

**Rejected: moving `ImportStatement` out of `journal.py` instead.** Nine
test files use it, imported from `journal.py`, and a re-export from `journal.py`
would recreate the cycle.

---

## 3. Rules

### 3.1 Rule-file keys

```toml
[[rule]]
transfer = "Savings"
note = "standing order to savings"
[rule.when]
iban = "DE44500105175407324931"
direction = "out"

[[rule]]
remittance = "IndianBank"
unit = "INR"
[rule.when]
counterparty = "Fernweh Transfer"
```

- **Exactly one action key per rule**: `account`, `transfer` or `remittance`.
  Its value is a non-empty account name. `account` keeps today's meaning, a
  category, whatever the account's type (spec: an existing rule naming an
  asset clearing account keeps its meaning).
- **`unit`** is required with `remittance` and refused with the other two. It
  names a currency unit other than the base currency. No code names INR.
- **Why the key names the kind.** The spec requires a key distinct from
  `account`. Naming the kind in the key (`transfer = "Savings"`) reads as what
  it does, and it cannot express a kind without a counterpart, or two
  counterparts. A `kind = "transfer"` key beside `account` was rejected,
  because the spec rules out reusing `account`, and because a missing `kind`
  would then mean "category" silently.
- **Why `unit` is a sibling key and not an inline table**
  (`remittance = { account = "IndianBank", unit = "INR" }`): one shape per
  value, and the error for a missing unit names a key the user can see.
- **Key order when rendered:** the action key, then `unit`, then `note`, then
  `[rule.when]`. A file with only `account` rules renders byte-for-byte as
  today, so `rule_set_base` is unchanged for every existing rule set, and
  every `base` line in a user's saved file stays valid.
- **The file header comment is not changed.** Changing it would change
  `show-rules` output, and the `base`, for every ledger. The new keys are
  documented in the guide instead.

### 3.2 Storage and identity

```python
class RuleKind(Enum):
    category = "category"
    transfer = "transfer"
    remittance = "remittance"

class Rule(base, Archivable):
    ...
    # Immutable, like condition and account_id: a classification's rule must
    # keep meaning what matched (CC §2.3).
    kind: Mapped[RuleKind] = mapped_column(SqlEnum(RuleKind), nullable=False,
                                           default=RuleKind.category, server_default="category")
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id"), nullable=True)
    unit: Mapped["Unit | None"] = relationship("Unit")
    # CHECK ck_rule_remittance_unit: (kind = 'remittance') = (unit_id IS NOT NULL)
```

- **The model carries a Python default as well as the server default**, for
  MC §5.1's reason: tests insert rows directly, and an expired attribute on a
  detached row fails.
- **`update_rule_service` does not take `kind` or `unit_id`,** so their
  immutability is structural, as for `condition` and `account_id`.
- **Identity** becomes `(when, kind, account_id, unit_id)`, in
  `plan_rule_changes` and in `parse_rule_file`'s duplicate check, which uses
  `(when, kind, account name, unit identifier)`. Changing the kind or the unit
  therefore retires the rule and adds a new one (spec).
- **Two rules with the same `when` and account but different kinds** are not
  duplicates. The first one wins, as for any overlap.
- `StoredRule`, `FileRule`, `PlannedRule` and `CompiledRule` gain `kind` and
  `unit_id`, and `StoredRule` gains `unit_identifier`. Each new field has a
  default and comes last, so `test_rule_matcher.py`'s positional
  `StoredRule(...)` and `CompiledRule` stay valid.
- `add_rule_service(ctx, condition, account_id, priority, note=None,
  kind=RuleKind.category, unit_id=None)`.
- `list_rules_service` joined-loads `Rule.unit`.
- `plan_rule_changes(stored, file, account_ids, base, unit_ids=None)`. The
  default keeps existing calls valid.

### 3.3 Checks when the file is applied

`_parse_file_rule` (pure):

| Problem | Error |
|---|---|
| No action key | `rule N, account: is required`, today's text, pinned by `test_rule_file.py` |
| Two action keys | `rule N, transfer: cannot be combined with account`, naming the later key |
| An action value that is not a non-empty string | today's `must be a non-empty string`, under that key |
| `unit` missing on a remittance | `rule N, unit: is required with remittance` |
| `unit` on a category or transfer rule | `rule N, unit: is only allowed with remittance` |

`_plan` (needs the ledger). The existing checks (the account exists and is a
leaf) run for every kind, under the rule's action key. Transfer and remittance
rules then add the spec's counterpart rules. Each failure is
`MalformedRuleFile(position, key, problem)`:

| Counterpart | Problem text |
|---|---|
| expense or income account, which includes both unclassified buckets | `'Groceries' is an expense account; a transfer's counterpart must be an own asset or liability account` |
| in the People subtree | `'Alice' is a People account; money to or from a person stays with split-line` |
| the pending bucket (by name) | `'Pending Remittances' is kohle's pending bucket` |
| remittance `unit` not found | `rule N, unit: no unit named 'INX'` |
| remittance `unit` not a currency, or the base currency | `rule N, unit: 'EUR' is not a currency other than EUR` |

- **"Own account" has one definition.** It is `accounts.own_account(account,
  people_ids)`: asset or liability, outside People. `balance_sheet_accounts`
  is rewritten to use the same predicate.
- **People are resolved tolerantly** by `accounts.people_account_ids(ctx)`,
  which returns an empty set when the `People` root does not exist, as
  budgeting's `_subtree` does for the unclassified bucket. The rule, reclassify
  and import tests seed no People root, so a strict lookup would make them
  fail.
- **The fourth check in the spec, "the importing account itself", is not
  here.** A rule is not tied to an importing account; one rule applies to
  every statement. §3.4 moves it to match time, and §17.1 asks the user to
  accept that.
- **`ApplyRulesError` gains `UnitError`,** for a failure of the unit lookup
  other than not-found.

### 3.4 Matching

```python
@dataclass(frozen=True, slots=True)
class CompiledRule:
    rule_id: int
    account_id: int                  # the target, or the counterpart for a transfer or remittance
    holds: Predicate
    kind: RuleKind = RuleKind.category
    unit_id: int | None = None

def match_rule(compiled, description, counterparty, amount,
               statement_account_id: int | None = None) -> CompiledRule | None
```

- **A transfer or remittance rule whose account is `statement_account_id` is
  skipped**, as if its conditions did not hold, and evaluation moves on to the
  next rule.
  - A move from Savings to Savings means nothing.
  - The natural rule, "counterparty is my own name → Savings", also matches
    Savings' own row. Failing the import there would push the user towards
    IBAN conditions for no gain, while skipping lets the same rule file serve
    every statement.
- **Category rules are not skipped.** Today a category rule aimed at the
  importing account posts a self-cancelling entry, and that stays as it is.
- **`match_rule` stays pure and session-free.** The new parameter is a plain
  int. It defaults to `None`, meaning no skip, so the existing four-argument
  calls in `test_rule_matcher.py` are unchanged. Both production callers pass
  it: the import passes the cash account, and `classify-rules` passes
  `statement_line(classification).account_id`.

### 3.5 What `list-rules` and the summaries show

- **`list-rules`** keeps its columns `id`, `account`, `conditions`. The
  `account` cell is `Savings` for a category rule (unchanged), `transfer
  Savings` for a transfer and `remittance IndianBank INR` for a remittance.
  This needs no new column, so a category-only table is unchanged.
- **`apply-rules` and `edit-rules`** summary lines use the same text: `rule 4
  (new) -> transfer Savings { … }`.
- One CLI helper, `_action_text(kind, account_name, unit_identifier)`, makes
  that text for all three places.

---

## 4. The classification record

### 4.1 Columns

```python
class ClassificationKind(Enum):
    category = "category"     # today's rows, and every row of a ledger without the new rules
    transfer = "transfer"     # the line is a move to final_account_id, an own account
    mirror = "mirror"         # the line is the other side of a transfer; its own posting is cancelled
    remittance = "remittance" # the line sits in the pending bucket until completed

class Classification(base, Archivable):
    ...existing columns...
    # What the line currently is. It changes alongside final_account_id; what
    # the engine first decided is still read from matched_rule_id (whose kind
    # is immutable) and proposed_account_id.
    kind: Mapped[ClassificationKind]       # NOT NULL, server default 'category'
    # The transfer this row was absorbed into, named by the entry id of the
    # transfer's statement line: the id every listing shows.
    mirror_of_entry_id: Mapped[int | None] # FK journal_entries.id, UNIQUE
    remittance_account_id: Mapped[int | None]  # FK accounts.id: the counterpart (IndianBank)
    remittance_unit_id: Mapped[int | None]     # FK units.id: the currency (INR)
    # The entry that currently completes the remittance; NULL while pending
    # and after uncomplete-remittance, as Split.adjusting_entry_id.
    completion_entry_id: Mapped[int | None]    # FK journal_entries.id, UNIQUE

    entry = relationship("JournalEntry", foreign_keys=[journal_entry_id])   # now three FKs to journal_entries
    remittance_account = relationship("Account", foreign_keys=[remittance_account_id])
    remittance_unit = relationship("Unit")
```

Constraints:

| Name | Rule | Why |
|---|---|---|
| `uq_classification_mirror_of` | UNIQUE(`mirror_of_entry_id`) | A transfer has at most one mirror. This makes a double absorption structurally impossible. |
| `ck_classification_mirror` | `(kind = 'mirror') = (mirror_of_entry_id IS NOT NULL)` | A mirror always names its transfer. |
| `ck_classification_remittance` | `(kind = 'remittance') = (remittance_account_id IS NOT NULL) AND (remittance_account_id IS NULL) = (remittance_unit_id IS NULL)` | A remittance always has its counterpart and unit, and nothing else carries them. |
| `uq_classification_completion` | UNIQUE(`completion_entry_id`) | One completion entry completes one remittance. |
| `ck_classification_completion` | `completion_entry_id IS NULL OR kind = 'remittance'` | |

- **`proposed_account_id` is never rewritten** (spec). It still locates the
  counterpart line for `post_correction`, `split-line` and
  `list-unclassified`.
- **`final_account_id` keeps meaning "where the line's value sits now".**
  - For a transfer it is the counterpart, B.
  - For a mirror it is the row's own account, B. Its bucket posting is
    cancelled onto B, so it nets to nothing (§5.4).
  - For a remittance it is the pending bucket, completed or not.
    `post_correction` reverses out of `final_account_id`, and a completed
    remittance is refused before it would (§7.1).
- **The direction is not stored.** `statement_amount` gives it exactly, from
  the line the record already points at: negative is outgoing. A stored copy
  could disagree with the entry, which can never change. §17.7 flags this
  against the spec's "records … the direction".

### 4.2 The states

| State | kind | proposed | matched_rule | rerun_rule | final | corrected | mirror_of | remittance acct / unit | completion |
|---|---|---|---|---|---|---|---|---|---|
| Category rule at import (today) | category | X | R | – | X | F | – | – | – |
| Fall-through (today) | category | bucket | – | – | bucket | F | – | – | – |
| Transfer rule at import | transfer | B | R (transfer) | – | B | F | – | – | – |
| `classify-rules` made it a transfer | transfer | bucket | – | R | B | F | – | – | – |
| `reclassify` onto an own account | transfer | unchanged | unchanged | unchanged | B | **T** | – | – | – |
| Absorbed at import or by a rule-made transfer | mirror | bucket | – | – | own account B | F | T's entry | – | – |
| Joined by `join-transfer` | mirror | bucket | – | – | B | **T** | T's entry | – | – |
| Unjoined by `unjoin-transfer` | category | bucket | – | – | bucket | **T** | – | – | – |
| Pending remittance, at import | remittance | Pending | R (remittance) | – | Pending | F | – | IndianBank / INR | – |
| Pending remittance, by `classify-rules` | remittance | bucket | – | R | Pending | F | – | IndianBank / INR | – |
| Completed | remittance | as above | | | Pending | F | – | IndianBank / INR | C |
| Completion reversed | remittance | as above | | | Pending | F | – | IndianBank / INR | NULL |

**The spec's five distinctions** (Goals, "Every classification stays
recorded"; issue 136):

- **A rule-made transfer:** `kind = transfer`, `corrected = false`.
- **An absorbed mirror, naming its move:** `kind = mirror` and
  `mirror_of_entry_id`.
- **A pending remittance, then completed, in either direction:** `kind =
  remittance`, with `completion_entry_id` NULL or set; the direction comes from
  the sign.
- **A human correction:** `corrected = true`, whatever the kind.
- **A category classification:** `kind = category`.

Every existing row migrates to `kind = category` with NULL in the new columns,
so a ledger without the new rules reads exactly as before.

### 4.3 Services (`classification_services.py`)

| Service | Kind | Change |
|---|---|---|
| `add_classification_service(..., kind=category, remittance_account_id=None, remittance_unit_id=None)` | create | defaults keep every caller |
| `set_classification_outcome_service(ctx, id, final_account_id, kind=category)` | update | Also sets `kind`, and clears the remittance columns when the kind is not `remittance`. `corrected = true` as today. |
| `set_rerun_outcome_service(ctx, id, final_account_id, rule_id, kind=category, remittance_account_id=None, remittance_unit_id=None)` | update | defaults keep today's call, which `test_classify_rules.py` monkeypatches on the `classification` module |
| `set_mirror_service(ctx, id, final_account_id, mirror_of_entry_id, by_human)` | update | **new.** `kind = mirror`; `corrected = corrected or by_human` |
| `clear_mirror_service(ctx, id, final_account_id, by_human)` | update | **new.** `kind = category`, `mirror_of_entry_id = NULL`; `corrected = corrected or by_human` |
| `set_completion_service(ctx, id, completion_entry_id \| None)` | update | **new** |
| `rerun_candidates_service(ctx, bucket_ids, statement_account_id=None)` | retrieve | Optional filter: the entry has a line on that account that is not the counterpart line. That gives "the untouched fall-throughs of account B". |
| `open_transfers_service(ctx, counterpart_id=None)` | retrieve | **new.** `kind = transfer` and no classification whose `mirror_of_entry_id` is this entry, optionally `final_account_id = counterpart_id`. It eager-loads the entry, its lines and the final account, in `(entry_date, entry id)` order. |
| `mirror_of_service(ctx, transfer_entry_id)` | retrieve | **new.** The mirror's classification, or `None`. |
| `pending_remittances_service(ctx)` | retrieve | **new.** `kind = remittance AND completion_entry_id IS NULL`, eager-loading the entry, its lines, `remittance_account` and `remittance_unit`. |
| `first_statement_dates_service(ctx, account_ids)` | retrieve | **new.** For each account that is the statement account of some classification, the earliest such entry date (§8). |

`journal_services.py`:

- `add_journal_entry_service(..., reverses_entry_id=None)`, and `post_entry`
  passes it through (135).
- `entry_by_id_service(ctx, entry_id)`, eager-loading lines and units (135).

---

## 5. Transfers

### 5.1 The move

A transfer rule posts exactly the entry a category rule would: the cash
account against the rule's account, here the counterpart B. Only the record
differs (`kind = transfer`). No new line shape and no new posting code is
needed, and the move "carries the date of whichever side posted it" (spec)
because it is the importing row's own entry.

A transfer is identified everywhere by **the entry id of the statement line
it was made from**. For a transfer made at import, that entry is the move
itself. For one made by `classify-rules` or `reclassify`, the move is the
adjusting entry, but the handle is still the original line, which is what
`list-unclassified`, `reclassify` and the new listings print (EC §2.4).

### 5.2 Mirror recognition: the pure part (`transfers.py`)

```python
MIRROR_WINDOW_DAYS = 3

@dataclass(frozen=True, slots=True)
class TransferSide:
    entry_id: int
    entry_date: date
    amount: Decimal            # signed, on the statement the transfer was made from
    counterpart_id: int
    source_iban: str | None    # the statement account's IBAN, normalised, if it has one

@dataclass(frozen=True, slots=True)
class RowSide:
    entry_date: date
    amount: Decimal            # signed, on the counterpart's statement
    counterparty_iban: str | None

def is_mirror(transfer: TransferSide, row: RowSide) -> bool:
    # opposite direction and exactly equal: one comparison
    return (
        row.amount == -transfer.amount
        and abs((row.entry_date - transfer.entry_date).days) <= MIRROR_WINDOW_DAYS
        and (transfer.source_iban is None or row.counterparty_iban is None
             or normalise_iban(row.counterparty_iban) == transfer.source_iban)
    )

def nearest_transfer(row: RowSide, transfers: Iterable[TransferSide]) -> TransferSide | None
    # among is_mirror hits: min by (|days|, transfer.entry_date, transfer.entry_id)
def nearest_row(transfer: TransferSide, rows: Iterable[tuple[int, RowSide]]) -> int | None
    # rows keyed by entry id; min by (|days|, row.entry_date, entry id)
```

- **"Opposite direction" and "exactly equal" are one test,** `row.amount ==
  -transfer.amount`. This covers an outgoing transfer (−500 on Checking, +500
  on Savings) and one made by an inbound rule (+500 on Savings, −500 on
  Checking). Decimals compare numerically, so `500.00` equals the stored
  `500.00000000`.
- **The window is inclusive** at ±3 calendar days (spec; the user's figure).
  It is a module constant, not a setting, because the user fixed it.
- **The IBAN check** compares the transfer's source account IBAN
  (`accounts.iban`) with the row's counterparty IBAN, both through the existing
  `normalise_iban`. It applies only when both are known (spec).
- **Ties are broken by** distance, then the earlier date, then the lower entry
  id. That is a total order, so pairing is deterministic (spec).
- **Pairing is greedy, in the order rows are processed:** statement order at
  import, `(date, entry id)` in `classify-rules`. Global optimal matching was
  rejected (§15).
- **No session, no I/O.** These are tested as a table without a fixture (§18).

### 5.3 Where the lookup runs (the spec's open question)

**Inside `ImportStatement`'s own closure, in its one transaction, before
`match_rule`.** No `UnitOfWork` is called from the loop.

1. Before the loop, `transfers.open_transfers_into(ctx, account.id, ibans)`
   loads the transfers into the importing account that have no mirror,
   through `open_transfers_service(ctx, account.id)` (a `crud_retrieve`
   service), and converts them to `TransferSide` values. `ibans` comes from one
   `list_accounts_service` call.
2. For each `CashRow`, the pure `nearest_transfer(row_side, open)` runs
   **before** `match_rule`. A hit is absorbed (§5.4) and removed from `open`,
   so it cannot pair twice within the statement. No rule is evaluated for that
   row (spec: "no rule can also classify a mirror").
3. Otherwise `match_rule(..., statement_account_id=account.id)` runs as
   today.

Loading once per statement is enough. Transfers posted during this import
have counterparts other than the importing account (§3.4), so none of them can
be a row's partner in the same statement. The rule matcher's own contract is
untouched: it is pure, its input is the compiled list, and the new parameter
is a plain id.

### 5.4 How an absorbed row is stored (the spec's open question)

**An absorbed row is posted as its own fall-through, then moved onto its own
account by an adjusting entry, in the same transaction.**

```
M  (the row, its native reference)   Savings dr 500   /  Unclassified Income cr 500
J  "Mirror: <description>"           Unclassified Income dr 500  /  Savings cr 500
```

M's classification: `kind = mirror`, `proposed = Unclassified Income`,
`final = Savings`, `mirror_of_entry_id = T`. J is exactly
`post_correction(M, to=Savings)`.

```python
def absorb(ctx, mirror: Classification, transfer_entry_id: int, *, by_human: bool) -> Result[JournalEntry, …]:
    own = statement_line(mirror).account_id
    post_correction(ctx, mirror, own, f"Mirror: {mirror.entry.description}")
    set_mirror_service(ctx, mirror.id, own, transfer_entry_id, by_human)

def unabsorb(ctx, mirror: Classification, *, by_human: bool) -> Result[JournalEntry, …]:
    bucket = fall-through bucket by the sign of statement_amount(mirror)   # the import's own rule
    post_correction(ctx, mirror, bucket, f"Unmirror: {mirror.entry.description}")
    clear_mirror_service(ctx, mirror.id, bucket, by_human)
```

**Why this shape.**

- **It is the same shape every path produces.** A join cancels a fall-through
  that already exists. The "first was a fall-through, then the transfer rule
  fired" case cancels one in the same import (spec). Import absorption is the
  third. With this storage all three are "a fall-through, then `absorb`", and
  the entries are identical whichever statement is imported first. Only the
  move's date differs.
- **Every later correction keeps working with no special case.** After an
  `unabsorb`, the row is an ordinary fall-through whose counterpart line is on
  the bucket in its own entry. So `list-unclassified`, `reclassify`,
  `split-line`, `classify-rules` and `join-transfer` work on it unchanged.
- **The native reference is recorded** in M, so `existing_references_service`
  skips the row on re-import with no change to dedup (spec Non-Goal).
- **"Absorbing posts no second move" holds.** M and J net to zero on both
  accounts. No balance anywhere includes the row; T alone moved the money.

**The cost, flagged in §17.5.** `entries-in-period Savings` shows M and J as
a +500/−500 pair beside T, and `entries-in-period "Unclassified Income"` shows
a net-zero pair. Balances, `list-unclassified`, `budget` (M and J share a
date) and every report are unaffected.

The alternatives, an entry with no lines and a self-cancelling pair on B,
were rejected because neither leaves a counterpart line that a later
correction can find (§15).

**`unabsorb` returns the row to the bucket of its direction,** not to
`proposed_account_id`. A join may take a line that a rule first sent to
`Groceries` and a human then moved into the bucket. Unjoining must put it back
in the bucket (issue 130), not in `Groceries`. For every other path the two
are the same account.

### 5.5 The import loop

```
(unchanged up to the buckets and the compiled rules)
ibans  = account_ibans(ctx)                         # {account id: normalised IBAN | None}
open   = open_transfers_into(ctx, account.id, ibans)
pending_id = None                                   # created on first remittance (§9.1)

for each CashRow:
    side = RowSide(row.entry_date, row.amount, counterparty.iban)
    hit  = nearest_transfer(side, open)
    if hit:
        post the fall-through entry and its classification, exactly as today with no rule
        absorb(ctx, that classification, hit.entry_id, by_human=False)
        open.remove(hit); continue
    matched = match_rule(compiled, …, row.amount, statement_account_id=account.id)
    counterpart_id = bucket | matched.account_id | pending bucket (remittance)
    post the entry as today
    add_classification_service(…, kind = category | transfer | remittance,
                               remittance_account_id / unit_id from the rule)
    if matched is a transfer:
        absorb_counterpart_fall_through(ctx, that classification, (expense_id, income_id), ibans)
```

`absorb_counterpart_fall_through(ctx, transfer, bucket_ids, ibans) ->
Result[int | None, …]` is in `transfers.py`. It:

- loads B's untouched fall-throughs through `rerun_candidates_service(ctx,
  bucket_ids, statement_account_id=B)`, the same set `classify-rules` is
  allowed to move;
- picks with `nearest_row`; and
- absorbs the pick with `by_human=False`.

It queries per transfer row, so a second transfer in the same statement sees
the first one's absorption.

Both import orders, with a rule on each side (`iban = <Savings IBAN>` →
`transfer = "Savings"` and `iban = <Checking IBAN>` → `transfer = "Checking"`):

| Order | Checking's −500 (04-03) | Savings' +500 (04-04) | Move dated |
|---|---|---|---|
| Checking first | transfer rule → T into Savings; nothing on Savings yet | nearest open transfer T → absorbed as M + J | 04-03 |
| Savings first | nearest open transfer T′ → absorbed as M′ + J′ | inbound rule → T′ into Checking; nothing on Checking yet | 04-04 |
| Savings first, rule on Checking only | transfer rule → T; then Savings' fall-through F is absorbed (J) | fell through as F | 04-03 |

The third row is why the spec's "dated 2026-04-04 when Savings is imported
first" needs a rule that matches Savings' row too (§17.2).

**What does not change.**

- `SecurityRow`s are untouched.
- The import still returns the row count. An absorbed row counts, because it
  was imported. `ImportStatement`'s `int` result is pinned by tests.
- A ledger without transfer rules runs one extra read query per import, which
  finds nothing and writes nothing.

---

## 6. `classify-rules` with transfer and remittance rules

### 6.1 The plan, in three phases

Candidates are today's untouched fall-throughs (CC §7.2), in `(date, entry
id)` order. Every candidate is matched once, with
`statement_account_id=statement_line(c).account_id`. Then:

1. **Mirrors of existing transfers, before any rule** (spec: "mirror
   recognition runs before any rule"). `open_transfers_service(ctx)` is loaded
   once and grouped by counterpart. Each candidate, in order, takes its
   `nearest_transfer` into its own account. Both are claimed.
2. **Transfer decisions.** Each unclaimed candidate whose rule is a transfer
   claims its counterpart's `nearest_row` among the unclaimed candidates. That
   becomes a transfer move plus a mirror move, and both are claimed.
3. **Everything else.** Each unclaimed candidate gets its category or
   remittance move. Today's "a rule aimed at the bucket the line is already in
   moves nothing" stays.

- **Phase 2 before phase 3 is what "mirror recognition before any rule"
  means within one run.** A fall-through that is the mirror of a transfer made
  in this run is absorbed, even if a category rule would also match it. With
  symmetric transfer rules on both sides, the earlier candidate makes the move
  and absorbs the other.
- **The non-leaf check** (CC §7.5 step 5) runs over category and transfer
  targets. A remittance targets the pending bucket, which kohle creates as a
  leaf, and its counterpart is checked by `validate_lines` at completion.
- **The plan stays read-only.** It never creates the pending bucket; the
  apply does (§9.1).

### 6.2 `RerunMove`

```python
@dataclass(frozen=True, slots=True)
class RerunMove:
    entry_id: int
    entry_date: date
    description: str
    amount: Decimal
    bucket_name: str
    rule_id: int | None          # None for a mirror: no rule moved it, a transfer absorbed it
    account_id: int              # the rule's account: target, or counterpart for a remittance;
                                 # the line's own account for a mirror
    account_name: str
    kind: ClassificationKind = ClassificationKind.category
    mirror_of: int | None = None
    unit_id: int | None = None
    unit_identifier: str | None = None

    @property
    def key(self): return (self.entry_id, self.rule_id, self.account_id, self.kind, self.mirror_of)
```

### 6.3 Apply

`ApplyClassifyRules` re-plans and compares keys, as today. Then, per move, in
plan order:

| kind | Posting | Record |
|---|---|---|
| category | `post_correction(to=account_id, "Classify: …")` | `set_rerun_outcome_service(id, account_id, rule_id)`, today's call |
| transfer | `post_correction(to=B, "Classify: …")` | `set_rerun_outcome_service(id, B, rule_id, kind=transfer)` |
| remittance | `pending = get_or_create_account(...)`; `post_correction(to=pending, "Classify: …")` | `set_rerun_outcome_service(id, pending, rule_id, kind=remittance, remittance_account_id=account_id, remittance_unit_id=unit_id)` |
| mirror | `absorb(ctx, c, mirror_of, by_human=False)` | inside `absorb` |

- Rule moves keep calling `set_rerun_outcome_service` through the
  `classification` module's namespace, so
  `test_a_fault_on_the_second_move_rolls_the_first_back` still intercepts them.
- Everything happens in one transaction and one `OperationGroup`.

### 6.4 The preview

The columns stay `entry_id, date, description, amount, from, to, rule`. A
`kind` column is added only when some move is not a category, so existing
output is unchanged:

| kind | `to` | `rule` | `kind` cell |
|---|---|---|---|
| category | account | id | `category` |
| transfer | B | id | `transfer` |
| mirror | B | `-` | `mirror of 12` |
| remittance | `Pending Remittances` | id | `remittance IndianBank INR` |

`Moved N line(s)` counts mirrors, since the preview showed them (spec).

---

## 7. Corrections

### 7.1 `reclassify`: leave the current state, enter the target state

The target is an "own account" by `own_account` (§3.3). The target account
type decides the path. That is not the inference the spec forbids for rules:
the spec mandates it for `reclassify`.

| Current state | Target is a category (incl. a bucket or a People account) | Target is an own account B |
|---|---|---|
| category | today's path, unchanged | `post_correction(to=B)`; outcome `kind=transfer`; then `absorb_counterpart_fall_through` |
| transfer (final C) | `unabsorb` its mirror if any (`by_human=False`); `post_correction(to=target)`; `kind=category` | `unabsorb` its mirror; `post_correction(to=B)`; `kind=transfer`; absorb B's fall-through |
| mirror | refused: `IsAMirror(entry, transfer)`, "unjoin-transfer N first" | refused, the same |
| remittance, pending | `post_correction(to=target)` out of the pending bucket; `kind=category`; remittance columns cleared | `post_correction(to=B)`; `kind=transfer`; absorb |
| remittance, completed | refused: `RemittanceCompleted`, "uncomplete-remittance N first" | refused, the same |

Order of checks inside `Reclassify`:

1. the split guard (today, first);
2. the classification;
3. the target account;
4. the state refusals;
5. the target refusals;
6. leave, move, record, enter.

Target refusals, own accounts only, as `InvalidTransferTarget(account,
reason)`:

- **the pending bucket**, because the spec forbids it as a counterpart;
- **the line's own statement account**, because a transfer needs two
  accounts. Today this posts a self-cancelling entry. It is refused only on
  the own-account path, which the spec changes anyway.

- **The mirror goes back to its bucket** when its transfer is reclassified
  (spec). It is unabsorbed with `by_human=False`, so a mirror that was
  absorbed automatically becomes an untouched fall-through again, and a joined
  one stays `corrected`.
- **Every leg is an adjusting entry dated at its own line,** all in one
  transaction and one group (spec: all or nothing).
- **The return value stays the main adjusting entry.** `Reclassify`'s
  `JournalEntry` result is pinned by tests, so the CLI message is unchanged.

### 7.2 `join-transfer LINE_ENTRY TRANSFER_ENTRY` and `unjoin-transfer LINE_ENTRY`

`JoinTransfer.execute(line_entry_id, transfer_entry_id)` refuses, in this
order:

| Condition | Error |
|---|---|
| the line is not a fall-through: kind category, final account in a bucket, not currently split | `NotAFallThrough(line)` |
| the transfer entry is not `kind = transfer` | `NotATransfer(transfer)` |
| the transfer already has a mirror | `TransferHasMirror(transfer, mirror)`, naming `unjoin-transfer` |
| the line's statement account is not the transfer's counterpart | `NotTheMirror(line, transfer, "it was imported into Checking, not Savings")` |
| the amounts differ or go the same way (`statement_amount(line) != -statement_amount(transfer)`) | `NotTheMirror(…, "its amount is 450.00, the transfer's is −500.00")` |

The first three and the counterpart check are the issue's. The amount check is
added, because joining a different amount cancels the wrong figure and leaves
the account off its statement. Different amounts are a spec Non-Goal (§17.6).
The window and the IBAN are deliberately not checked: overriding them is the
point of a join.

On success: `absorb(ctx, line, transfer_entry_id, by_human=True)`. The record
becomes `kind = mirror`, `corrected = true`, which is distinguishable from a
rule-made transfer and from a category correction (issue 130).

`UnjoinTransfer.execute(line_entry_id)` refuses a line that is not `kind =
mirror` (`NotAMirror`). Otherwise it runs `unabsorb(ctx, line,
by_human=True)`. The row goes back to its bucket as a human-corrected
fall-through. It no longer qualifies for automatic absorption or
`classify-rules`: the human has said it is not this transfer's mirror.

It takes the mirror's entry, not the transfer's, because the mirror is the
line the user is correcting, which is the `split-line` / `unsplit-line`
pattern.

### 7.3 `split-line`

`SplitImportedEntry` refuses any `kind` other than `category`, with
`NotSplittable(entry, reason)` (a `SplitError`):

- `it is a transfer`;
- `it is the mirror of transfer 12`;
- `it is a remittance`.

This covers a completed remittance as well as a pending one. The spec names
only "pending", but splitting a completed one would take shares out of the
cleared pending bucket. The refusal comes after the classification lookup,
before anything is posted.

---

## 8. Transfers awaiting a mirror

`ListUnmirroredTransfers.execute() -> list[UnmirroredTransfer]` is read-only:

```python
@dataclass(frozen=True, slots=True)
class UnmirroredTransfer:
    entry_id: int
    entry_date: date
    description: str
    amount: Decimal          # signed, on the statement the transfer was made from
    account_name: str        # that statement's account
    counterpart_name: str
```

- **Which transfers.** `open_transfers_service(ctx)` returns every transfer
  without a mirror. The use case keeps those whose counterpart appears in
  `first_statement_dates_service`, which means it has had at least one
  statement row imported and classified, and whose date is no earlier than
  that account's first statement row minus the window.
- **What "has had a statement imported" means.** It means "is the statement
  account of some classification". Mirrors are cash rows, and every imported
  cash row gets a classification. That rules out a broker account imported
  only with trades. It also needs no knowledge of the `id:reference` format.
- **The lower date bound is a design addition** (§17.8). Without it, a user
  who starts importing Savings in June sees every pre-June transfer to Savings
  listed for ever, though no statement will ever bring their mirrors.
- **Output.** Ordered by date, then entry id. The columns are `entry_id`,
  `date`, `description`, `amount`, `account` and `counterpart`. An empty list
  prints `No transfers awaiting a mirror`.

---

## 9. Remittances

### 9.1 The pending bucket

- **Name: `Pending Remittances`,** the `PENDING_REMITTANCES` constant in
  `accounts.py`, next to the other well-known account names. It reads like
  `Unclassified Expense`, and it is neutral between the two directions: the
  bucket holds euros in transit (positive) for an outgoing remittance and an
  offset (negative) for an incoming one.
- **Type `asset`, a root account.** Net worth counts it as an own account,
  which is exactly the spec's "euros in transit at face value" (outgoing) and
  "nothing counted twice" (incoming: Checking +1,100 and Pending −1,100).
- **Created on first use,** through `get_or_create_account`: by the import
  loop at its first remittance match, and by `ApplyClassifyRules` at its first
  remittance move. It is never created up front, as the unclassified buckets
  are, because that would add an account to `list-accounts` for every ledger,
  which is a regression.

### 9.2 Posting at import

A remittance rule posts the cash account against the pending bucket, the same
two lines as a category, and records `kind = remittance` with the rule's
counterpart and unit. Mirror recognition never touches remittances.
`open_transfers_service` selects `kind = transfer` only, and fall-through
candidates are `kind = category` in a bucket (issue 132).

### 9.3 Pending remittances get their own listing

`list-pending-remittances` (read-only):

```python
@dataclass(frozen=True, slots=True)
class PendingRemittance:
    entry_id: int
    entry_date: date
    description: str
    direction: Direction          # conditions.Direction: out or in, from the sign
    amount: Decimal               # X, unsigned
    account_name: str             # the euro account
    counterpart_name: str
    unit_identifier: str
```

The columns are `entry_id`, `date`, `description`, `direction`, `amount`,
`account`, `counterpart` and `unit`. An empty list prints `No pending
remittances`.

**Why not `list-unclassified`.**

- `list-unclassified` is "the queue of lines that need a rule or a manual
  correction" (the guide), selected by `final_account_id IN buckets` (EC
  §6.1). A pending remittance has been classified by a rule. What it needs is
  a number, through a different command.
- It also needs columns `list-unclassified` lacks: direction, counterpart and
  unit.
- Mixing the two would change `list-unclassified`'s predicate and its
  columns.

### 9.4 Completion

```python
def complete_remittance(ctx, classification: Classification, quantity: Decimal) -> Result[JournalEntry, RemittanceError]
```

This is a ctx-taking function. The Indian bank importer can call it from
inside its own import transaction when its currency row is the remittance's
mirror (spec). `CompleteRemittance.execute(entry_id, quantity)` is a thin
`UnitOfWork` over it.

1. Refuse `NotARemittance` unless `kind = remittance`. Refuse
   `RemittanceCompleted` if `completion_entry_id` is set.
2. `x = abs(statement_amount(c))`. It is outgoing when `statement_amount < 0`.
3. Build the lines with the existing `_cross_unit_lines(holding_account_id =
   remittance_account_id, holding_unit_id = remittance_unit_id, quantity = Y,
   unit_price = Total(x), cash_account_id = final_account_id (the pending
   bucket), cash_unit_id = the original line's unit, into_holding =
   outgoing)`:

   | Direction | Lines | MC form |
   |---|---|---|
   | outgoing | `IndianBank dr INR Y cost=X` · `Pending cr EUR X @1` | issue 111, the remittance |
   | incoming | `IndianBank cr INR Y cost=X` · `Pending dr EUR X @1` | issue 115, the reconversion |

4. `post_entry` dated `classification.entry.entry_date`, with reference
   `uuid4().hex` and description `Complete: <description>`.
5. `set_completion_service(id, entry.id)`.
6. **Incoming only:** `line_costs(ctx, entry.lines)`. On `Err`, return it,
   and the transaction rolls back.

- **The rate is never typed.** X / Y is implicit in `cost = X` over quantity
  Y. The lot costs exactly X (MC §2.1, `Fraction` lot costs). Testable:
  1,012.00 EUR and 90,000 INR give one lot of exactly 1,012.00.
- **FIFO sees the lot on the day the euros left,** because the completion is
  dated at the original line, and MC's order-independence covers backdating.
  The same-date caveat is inherited (§17.10).
- **The gain on an incoming completion** is the replay's ordinary disposal:
  `Sale(proceeds = X, fifo_cost = consumed)`. With one lot of 90,000 INR at
  1,012.00 and X = 1,100.00, `realised` shows 88.00 under `INR`.
- **The shortfall check.** The spec says a shortfall "fails … and writes
  nothing", but MC's shortfall is a read-time failure: `record` accepts the
  entry and the reports fail. So a completion that consumes lots replays the
  currency lots inside its own transaction. `line_costs` is the existing loader
  and replay; it reads lots and never prices, so the price guards hold.
  - Only the incoming direction consumes lots. An outgoing completion only adds
    a lot, which can never cause a shortfall, so it skips the replay, as
    "no error handling for impossible cases" asks.
  - **Consequence:** on a ledger whose replay already fails elsewhere, an
    incoming completion is refused with that existing failure. Every report on
    that ledger already fails the same way (§17.3).
- **Recording reads no fetched price.** Nothing here touches `prices`.
  `remittances.py` joins `RECORDING_MODULES` in the guard test.

### 9.5 Reversing a completion: `uncomplete-remittance ENTRY_ID`

**The problem an ordinary reversal cannot solve.** Mirroring the completion's
lines as an ordinary entry does not undo it:

- **Incoming.** The mirrored `IndianBank dr INR 90000 cost=1100` is a *new*
  lot at 1,100.00, and the original disposal still realises 88.00. Issue 135
  requires that the consumed lots come back and the gain is un-realised.
- **Outgoing.** The mirrored `IndianBank cr INR 90000 cost=1012` is a disposal
  that FIFO takes from the **oldest** lot, not the one the completion created.
  It realises a gain or loss that never happened.

**Decision: `journal_entries.reverses_entry_id`, and a replay rule.**

```python
class JournalEntry:
    # The entry this one exactly reverses. The lot replay treats an entry and
    # its reversal as if neither were recorded; everything else reads both.
    reverses_entry_id: Mapped[int | None]   # FK journal_entries.id, UNIQUE
```

- **`posting.post_reversal(ctx, entry, description)`** posts every line of
  `entry` with its side flipped. It carries `quantity`, `unit_price`, `cost`
  and `price_unit_id` unchanged. It is dated `entry.entry_date` and sets
  `reverses_entry_id = entry.id`. UNIQUE makes a second reversal of the same
  entry impossible.
- **The replay rule, in `lots.replay`:**
  - In the pass that groups lines by entry, collect every
    `entry.reverses_entry_id`.
  - An entry in that set, or one that has `reverses_entry_id`, is skipped for
    lots, sales, moves and the People check.
  - Each of its lot-valued lines is given its own face value as its cost.
  - The pair then nets to exactly zero in the moving-average fold, which reads
    `costs`. Every currency line is in `costs`, so the fold's basis for a
    currency is additive.
- **What that gives.** The lots are exactly as if the completion had never
  been recorded, with their dates and costs. The sale disappears, so the gain
  is un-realised. EUR lines are not lot-valued and net at face, as always.
- **The use case.** `UncompleteRemittance.execute(entry_id)`:
  1. Refuse `NotARemittance`. Refuse `RemittanceNotCompleted` unless
     `completion_entry_id` is set.
  2. Load the completion entry (`entry_by_id_service`).
  3. `post_reversal(…, "Uncomplete: <description>")`.
  4. `set_completion_service(id, None)`.
  5. **Outgoing only:** `line_costs` as in §9.4. Removing an acquisition can
     starve a later spend, for example 50,000 INR of groceries recorded after
     the completion. Reversing an incoming completion only gives lots back, so
     it needs no check.
- **The redo.** The user runs `complete-remittance` again with the right Y.
  That gives two commands and two groups, as issue 135 describes. A redo needs
  no extra check: if the reversal passed, later spends were satisfiable without
  this remittance's lot, and any new lot only adds to that.
- **The audit trail keeps every step:** C, R (pointing at C) and C2, plus the
  `classifications` updates (spec: nothing edited or deleted).

**Why a column on the ledger and not on the classification.** The replay
receives lines with their entries eagerly loaded
(`joinedload(JournalLine.entry)`). The link is therefore already in its input,
with no extra query and no knowledge of classifications. A
classification-side marker would need both loaders (`line_costs`,
`replay_ledger`) to run a second query and join it in. The link is also the
primitive `undo-delete-edit` needs for compensations that must not realise
anything (MC §13.11 noted that an exact reversal "is not expressible").

**Limit, recorded.** The moving-average fold for **securities** does not use
`costs`. A reversed security entry would net exactly in lots and `realised`
but not in `balance`'s average cost. Nothing in this spec reverses a security
entry, and `undo-delete-edit` must extend the rule if it does.

---

## 10. CLI

Every new command registers `writes=` explicitly, and `tests/test_reader.py`'s
`_WRITE_ARGV` / `_read_argv` gain the entries
(`test_write_argv_covers_exactly_the_write_commands` requires it). Errors are
`str(err)` and exit 1, as everywhere.

| Command | `writes` | Arguments | Output |
|---|---|---|---|
| `list-unmirrored-transfers` | False | – | table (§8), or `No transfers awaiting a mirror` |
| `join-transfer` | True | `LINE_ENTRY TRANSFER_ENTRY` | `Joined entry 7 to transfer 3` |
| `unjoin-transfer` | True | `LINE_ENTRY` | `Unjoined entry 7 from transfer 3` |
| `list-pending-remittances` | False | – | table (§9.3), or `No pending remittances` |
| `complete-remittance` | True | `ENTRY_ID AMOUNT` | `Completed remittance 12: 90000 INR for 1012.00 EUR` |
| `uncomplete-remittance` | True | `ENTRY_ID` | `Remittance 12 is pending again` |

- **`AMOUNT`** is the currency quantity: received for an outgoing remittance,
  paid out for an incoming one. It is a `DECIMAL`, and one that is not above 0
  is refused as `click.BadParameter` (exit 2) before any session, as `record`
  does for `--total`.
- **The names** follow the existing vocabulary: `list-*` for read-only queues
  (`list-unclassified`), and a verb with its `un-` inverse for a correction
  and its undo (`split-line` / `unsplit-line`). `join-transfer` and
  `unjoin-transfer` are the spec's working names, kept.
  `list-unmirrored-transfers` is long but says exactly what it lists.
  `cli-command-naming` may rename any of them. Use cases do not know the
  names, which appear only in the CLI and in the hint texts of
  `TransferHasMirror`, `IsAMirror` and `RemittanceCompleted`.
- **Wording.** The implementer settles the exact output wording with the docs
  pages, as MC §6.1 allowed.
- **Changed output, only when the new kinds exist:**
  - the `list-rules` and summary `account` text (§3.5);
  - `classify-rules`' `kind` column (§6.4).

---

## 11. Errors (`kohle/domain/domain_errors.py`)

```python
# ClassificationError family
NotAFallThrough(entry_id)              # "Entry 7 is not in an unclassified bucket; only a fall-through line can be joined"
NotATransfer(entry_id)                 # "Entry 3 is not a transfer"
TransferHasMirror(entry_id, mirror_id) # "Transfer 3 already has a mirror, entry 9; unjoin-transfer 9 first"
NotTheMirror(line_id, transfer_id, reason)
NotAMirror(entry_id)                   # unjoin of anything else
IsAMirror(entry_id, transfer_id)       # "Entry 9 is the mirror of transfer 3; unjoin-transfer 9 first"
InvalidTransferTarget(account, reason) # reclassify onto the pending bucket or onto the line's own account
NotARemittance(entry_id)
RemittanceCompleted(entry_id, completion_entry_id)  # "…; uncomplete-remittance 12 first"
RemittanceNotCompleted(entry_id)

# SplitError family
NotSplittable(entry_id, reason)

JoinTransferError = AccountError | JournalError | ClassificationError | SplitError
ListTransfersError = AccountError | ClassificationError
RemittanceError = AccountError | JournalError | ClassificationError | LotError
ImportStatementError  += AccountError        # get_or_create_account can fail with any AccountError
ApplyRulesError       += UnitError
```

`ReclassifyError` and `ClassifyRulesError` are unchanged, because the new
refusals are `ClassificationError`s. Each new error defines `__str__`, and the
CLI never branches on a type.

---

## 12. Migrations (head today: `c7e2a9d4b185`)

| Slice | Migration | Upgrade | Downgrade refuses when |
|---|---|---|---|
| 126 | `<a>_transfer_rules.py`, down `c7e2a9d4b185` | batch `rules`: `kind` NOT NULL default `'category'`. Batch `classifications`: `kind` NOT NULL default `'category'`, `mirror_of_entry_id` + FK + UNIQUE, `ck_classification_mirror`. | any rule or classification is not `category`, or any `mirror_of_entry_id` is set |
| 132 | `<b>_remittance_rules.py`, down `<a>` | batch `rules`: `unit_id` + FK, `ck_rule_remittance_unit`. Batch `classifications`: `remittance_account_id`, `remittance_unit_id`, `completion_entry_id` (+ FKs, UNIQUE), `ck_classification_remittance`, `ck_classification_completion`. | any of those columns is set |
| 135 | `<c>_entry_reversals.py`, down `<b>` | batch `journal_entries`: `reverses_entry_id` + self-FK + UNIQUE | any `reverses_entry_id` is set |

- **Batch mode throughout.** SQLite cannot add a FK or a CHECK in place (MC §9:
  a plain `add_column` with a FK fails part-way). `_upgrade_to_head` runs with
  foreign keys off, so rebuilding `journal_entries` under its referrers is safe
  (CC §2.4).
- **Each downgrade** opens with `_refuse_if_unrepresentable`, counting before
  any schema statement, as in `d7f3b9a1c846`.
- **`HEAD_REVISION`** follows each migration.
- **Three, not five.** The mirror column is used from 127 but lands with
  126's `classifications` rebuild, and `completion_entry_id` (133) lands with
  132's. This is CC §15 item 1's reasoning, "one migration per table per
  feature half is simpler", applied to adjacent slices. `reverses_entry_id`
  stays separate: it is on the core ledger table, and only 135 uses it.

---

## 13. Docs

- **Two new fictional statements.** They keep every existing checked example
  byte-identical; adding rows to `statement.csv` would change nine examples'
  output.
  - `docs/examples/transfers.csv`: Checking, Deutsche Bank format, June 2026,
    with a transfer to Savings, a card payment to a fictional remittance
    service and a euro inflow from it.
  - `docs/examples/savings.csv`: Savings, the same format, with the mirror row.
- **`import-and-classification.md`:**
  - 126: transfer rules, the keys, the counterpart refusals, and why an
    `account =` rule to an asset account keeps its meaning;
  - 127: both import orders, re-import, a mirror outside the window;
  - 128: `classify-rules` with a transfer and its mirror;
  - 129: `list-unmirrored-transfers`;
  - 130: join and unjoin;
  - 131: corrections;
  - 132: remittance rules and `list-pending-remittances`.
- **`recording-entries.md`:**
  - 133: completion, the lot of exactly X, beside the existing `record
    --total` section;
  - 134: the incoming completion and its `realised` row;
  - 135: `uncomplete-remittance`.
- **Fictional data.** IBANs, accounts, counterparties and amounts are
  fictional (AGENTS.md). The remittance service is named `Fernweh Transfer`,
  not a real brand.

---

## 14. The decision categories

### State and data lifecycle

- **Units of work.** Each of these is one `UnitOfWork`, which is one SQLite
  transaction and one `OperationGroup`: an import, a `classify-rules` apply,
  `reclassify`, `join-transfer`, `unjoin-transfer`, `complete-remittance` and
  `uncomplete-remittance`. Every leg commits together or none does:
  - a transfer, its absorbed mirror and the fall-through cancellation;
  - a reclassify that un-absorbs a mirror;
  - a completion and its lot check.

  A crash part-way rolls back, and the lazily created group goes with it
  (spec: all or nothing, one group).
- **What must succeed together, and why.** A move without its mirror's
  cancellation double counts, and a cancellation without the record leaves an
  orphaned adjusting entry. That is why `absorb` and `unabsorb` are
  ctx-taking functions, never units of work (EC §5.2's trap, which bites
  harder inside the import loop).
- **Append-only ledger.** Every change is a new entry dated at its own line:
  the transfer move, `Mirror:`, `Unmirror:`, `Complete:` and `Uncomplete:`.
  Nothing is edited, voided or deleted.
- **The mutable annotation layer.** `classifications.kind`, `final_account_id`,
  `corrected`, `mirror_of_entry_id`, the remittance columns and
  `completion_entry_id` are updated through `crud_update`, so
  `list-operations` shows every step.
- **Reversible.**
  - A transfer is reversed by `reclassify`.
  - An absorption is reversed by `unjoin-transfer`.
  - A completion is reversed by `uncomplete-remittance`, which is exact even
    for lots, through `reverses_entry_id` (§9.5).
  - A retired rule never undoes a move (spec); only `classify-rules` moves
    anything.
- **Replayable.**
  - Re-importing writes nothing: the absorbed row's reference is stored in M.
  - Lots are rebuilt from the ledger on every read, and nothing lot-derived is
    stored (MC §2.3). The completion's lot check reads them and stores
    nothing.
- **Auditable.** Every leg is a `journal_entries` create or a `classifications`
  update in the command's one group.

### Error propagation

- **Pure functions return nothing to propagate.** `is_mirror`,
  `nearest_transfer`, `nearest_row` and `match_rule` return values, never
  errors.
- **Services** wrap infrastructure failures as `ClassificationError(str)`,
  `JournalError(str)` or `RuleError(str)`, unchanged, so nothing above them
  sees SQLAlchemy.
- **`transfers.py` and `remittances.py`** turn state violations into named
  `ClassificationError`s. Failures from `post_entry` (`JournalError`), from
  `line_costs` (`LotError`) and from account lookups (`AccountError`) pass
  through unchanged.
- **`transfers.py` knows the classification's anatomy** (§2.2 helpers), not
  the rule engine. `remittances.py` knows lots only through `line_costs`'
  `Result`.
- **Rules.** Counterpart problems become positioned `MalformedRuleFile`s in
  `_plan`, so `edit-rules` reopens the editor on them as on any file error (CC
  §10.1). A unit lookup failure other than not-found passes through as a
  `UnitError`.
- **The CLI** prints `str(err)` and exits 1. Flag-shape errors exit 2 before
  any session.

### Concurrency and ownership

- **Single-threaded, with no shared mutable state.** Each `kohle-cli` process
  opens one session per command.
- **Every list is a local of one call:** the open transfers, the claimed sets
  of the `classify-rules` plan, the IBAN map and the lazily resolved pending
  bucket id. Nothing is cached across commands, so a rule or transfer added
  between two imports takes effect.
- **Processes are serialised by SQLite's locking** and the busy timeout (DT
  §5).
- **No transaction stays open across a human.** `classify-rules` keeps its
  preview / re-plan / `ClassifyPlanChanged` guard. The plan's key now includes
  the kind and the mirror, so a concurrent import that creates or absorbs a
  mirror changes the plan and the apply refuses.
- **The other writing commands** (`join`, `unjoin`, `complete`, `uncomplete`)
  read, validate and write in one transaction, so no race exists within them.
- **The structural guards against a double write** are the UNIQUE constraints
  on `mirror_of_entry_id`, `completion_entry_id` and `reverses_entry_id`. They
  make a second absorption, completion or reversal of the same thing a
  constraint violation, even under a race the use cases did not foresee.
- **Reader devices** refuse the four new write commands before their bodies
  run.

### Reuse

**Used, not rebuilt:**

- `post_entry` and `validate_lines`;
- `_post_correction`, now `post_correction`, for every move: transfers by
  `classify-rules` and `reclassify`, absorption, un-absorption and joins;
- `_cross_unit_lines` with `Total`, for both completion forms, so a completion
  is literally MC's 111 or 115 entry;
- `lots.line_costs` and `replay`, for the lot check, the FIFO costs and the
  realised gain;
- `normalise_iban` and `conditions.Direction`;
- `rerun_candidates_service`, extended with one optional filter, as the single
  definition of "untouched fall-through" for `classify-rules`, import
  absorption and `reclassify` absorption;
- the strict bucket lookup and `get_or_create_account`;
- the own-account predicate of `balance_sheet_accounts`;
- the plan / re-plan / key-compare shape of `classify-rules`;
- `_refuse_if_unrepresentable`;
- the `pre_feature_baseline` oracle pattern;
- the docs harness.

**Introduced for the next piece of work:**

- **`post_reversal` and `reverses_entry_id` with the replay rule.** This is
  the compensation primitive `undo-delete-edit` proposes. A hand-recorded
  entry with a wrong amount could be undone the same way.
- **`complete_remittance(ctx, …)`**, for the Indian bank importer (spec).
- **`is_mirror` / `nearest_*` and `absorb`**, for `debts-and-liabilities`. A
  credit-card bill paid from Checking is a transfer to a liability, and once a
  card importer exists its statement's payment row is a mirror. That works
  with no change, since liability counterparts are allowed.
- **`statement_line` / `statement_amount`**, for anything that reads an
  imported line's own side.

### Extension points

| Extension | Seam | Contract |
|---|---|---|
| Indian bank importer completing a remittance | `remittances.complete_remittance(ctx, classification, quantity)` | ctx-taking and transaction-neutral. The importer finds the pending remittance its currency row mirrors, which is that brief's job, and passes the row's quantity. `CashRow` stays base-only (Non-Goal). |
| `undo-delete-edit` compensations | `posting.post_reversal`, `JournalEntry.reverses_entry_id` | A reversal exactly mirrors one entry. The replay ignores the pair. At most one reversal per entry. |
| A card or loan importer | none needed | A transfer rule to a liability counterpart works as is. |
| The ML phase | `classifications.kind`, `mirror_of_entry_id`, the remittance columns, `corrected`, `matched_rule_id`, `rerun_rule_id` | §4.2's state table is the label schema. |
| `cli-command-naming` | the CLI only | Use cases are name-free. |
| A configurable mirror window | **none, deliberately** | The user fixed 3 days. Making it a setting needs a forcing problem first. |
| Rule kinds | `RuleKind` | **Closed.** A new kind needs a key, a check, a match branch and a record shape, which is a spec, not a plugin. |

### Build vs. buy

| Component | Decision | Evaluated, and why not |
|---|---|---|
| Mirror matching | **Build**, `is_mirror` plus two `min` calls, about 30 lines | **beancount**'s `beancount.ingest.similar` and **smart_importer**: similarity on beancount's own entry model, scored, not the spec's exact amount, date window and IBAN rule. They would need the ledger exported. **hledger**'s CSV rules have no cross-statement pairing. **scipy**'s `linear_sum_assignment` gives optimal assignment, but the spec asks for nearest-first, and scipy is not a dependency. |
| Two-amount completion | **Reuse** `_cross_unit_lines(Total)` | It is the MC form. |
| Lot check and gain | **Reuse** `lots.line_costs` and `replay` | |
| Reversal netting | **Build**, one rule in `replay` | No library holds kohle's lot replay. |
| Storage | **Build**, columns and three migrations | A pairing table was rejected (§15). |
| CLI, tables | **Buy**: click, tabulate (existing) | |

### Abstractions introduced

| Abstraction | Forcing problem |
|---|---|
| `posting.py` (moved code) | The `journal → transfers → post_entry` cycle (§2.1), and the future importer's call into `remittances.py`. |
| `counterpart_line`, `statement_line`, `statement_amount` | Four modules need the same anatomy of an imported entry. The mirror IBAN check and the self-counterpart skip need the statement account, which nothing named before. |
| `RuleKind`, `Rule.kind`, `Rule.unit_id` | Kind must be explicit, never inferred from the account type (spec), and part of identity. |
| `ClassificationKind`, `Classification.kind` | A human-made transfer has no rule to read the kind from, and existing rows on asset accounts must not be reinterpreted. |
| `mirror_of_entry_id` (+ UNIQUE) | "An absorbed mirror names the move it joined" (spec). "Has no mirror yet" must be one query. |
| `remittance_account_id`, `remittance_unit_id` | The pending bucket is the final account, so the counterpart and unit need columns of their own (spec: the record holds them). |
| `completion_entry_id` | Pending versus completed, and the handle the reversal needs. |
| `reverses_entry_id`, `post_reversal`, the replay rule | Un-realising a gain append-only (§9.5). |
| `TransferSide`, `RowSide` | The pure matcher's inputs come from three sources: a `CashRow` at import, a fall-through classification and a transfer classification. ORM rows must not reach it. |
| `is_mirror`, `nearest_transfer`, `nearest_row` | The spec requires a pure, session-free matcher. |
| `absorb`, `unabsorb`, `absorb_counterpart_fall_through` | Five callers (import, `classify-rules`, `reclassify`, join, unjoin) must post and record identically. |
| `UnmirroredTransfer`, `PendingRemittance` | ORM rows cannot cross the session (EC §6.3). |
| `RerunMove` fields | The preview must show mirrors and kinds, and the key must catch their changes. |
| `own_account`, `people_account_ids` | One definition of "own", tolerant of a ledger with no People root. |
| `PENDING_REMITTANCES` | The bucket's one name. |
| The new errors | Distinct user messages. Nothing branches on them except tests. |

**Deliberately not introduced:**

- a pairing table;
- a transfer-group or "move id" column;
- a stored direction;
- a stored signed amount;
- a `source` enum (CC §14);
- a mirror-window setting;
- a separate `remittances` table;
- a generic state-machine class for `reclassify`. The table in §7.1 is a
  sequence of `if`s.

---

## 15. Alternatives rejected

| Rejected | Why |
|---|---|
| Infer transfer from the target being an asset | The spec forbids it, and it would turn existing `Transfers` clearing rules into transfers. |
| `kind = "transfer"` beside `account` | The spec wants a distinct key, and a missing `kind` would silently mean category (§3.1). |
| `remittance = { account, unit }` inline table | Two shapes for one value, and a less legible error key. |
| Check "counterpart is the importing account" at `apply-rules` | Impossible: rules apply to every statement (§3.4, §17.1). |
| Fail the import when a transfer rule matches its own counterpart's row | It forces IBAN conditions onto a natural own-name rule for no gain. |
| **An absorbed row as an entry with no lines** | It records the reference, but after an un-absorb there is no counterpart line for `reclassify`, `split-line` or `list-unclassified` to find. Each would need a special case in `post_correction`. |
| **An absorbed row as a self-cancelling pair on B** (`B dr / B cr`) | Both lines are on `proposed_account_id`, so "the counterpart line" is ambiguous. After an un-absorb, `post_correction` could pick the wrong side and add to the bucket instead of reversing. |
| A separate table of absorbed references | It changes dedup's lookup (spec Non-Goal) and drops the row's description and counterparty, which are training data. |
| A per-transfer clearing account (`Transfers`) | That is today's workaround, which the spec replaces with a direct move. |
| Mirror lookup inside `match_rule` | `match_rule` must stay pure, and a mirror check needs the open transfers. |
| A mirror lookup unit of work per row | A second transaction inside the loop (EC §5.2). |
| A query per row for open transfers | Loading once per statement is enough (§5.3). |
| Optimal (Hungarian) pairing across a statement | The spec asks for nearest date first. Greedy in statement order is deterministic and explainable. |
| Pending remittances in `list-unclassified` | They are classified, need a different action and other columns (§9.3). |
| Creating `Pending Remittances` on every import | It adds an account to every ledger, which is a regression. |
| A separate `remittances` table, as `splits` | A remittance is a classification outcome, not orthogonal to it. One row keeps "the classification of this line" single-referent. |
| Storing the direction | It is derivable exactly from the immutable entry (§4.1). |
| Reverse a completion by an ordinary mirrored entry | It realises a spurious gain or loss and does not restore lots (§9.5). |
| A reversal marker on the classification, read by the loaders | It needs a second query in both lot loaders, couples `lots.py` to classifications, and is useless to `undo-delete-edit`. |
| Run the lot replay after every remittance write | It blocks outgoing completions on a ledger already failing elsewhere, and checks cases that cannot fail. |
| A pre-write lot simulation instead of post-write replay | It duplicates the replay. The post-write replay in the same transaction is exact and rolls back. |
| Five migrations, one per schema slice | Three rebuilds of `classifications` for one feature half (§12). |
| Changing `ImportStatement`'s `int` result to report absorptions | The result is pinned by tests. The listings show absorption. |
| An optional `--redo Y` on `complete-remittance` | Issue 135 asks for reverse then redo, and two plain commands compose. |
| `reclassify` of a mirror doing unjoin + reclassify | It hides a pairing correction inside a category correction. A refusal that names `unjoin-transfer` is clearer. |

---

## 16. Issue mapping, order and scope changes

### 16.1 What lands where

| Issue | Lands |
|---|---|
| 126 | **First commit: the no-regression oracle (§18.6), from pre-feature code.** Then: migration a (minus the use of `mirror_of`). `RuleKind`, `ClassificationKind`. The rule-file `transfer` key, its render, identity and `_plan` checks. `own_account`, `people_account_ids`. `match_rule`'s skip. The import posts transfers with `kind = transfer`. `_action_text`. Docs. |
| 127 | **First commit: the §2.2 moves, behaviour-neutral.** Then `transfers.py`: the pure matcher, `absorb`, `absorb_counterpart_fall_through`, `open_transfers_into`. The import loop (§5.5). `set_mirror_service`, `open_transfers_service`, `rerun_candidates_service(statement_account_id)`. The Savings fixture and docs. |
| 128 | §6 for transfers and mirrors: the three-phase plan, `RerunMove` fields, the preview `kind` column. |
| 129 | §8: `first_statement_dates_service`, `ListUnmirroredTransfers`, the CLI. |
| 130 | §7.2: `unabsorb`, `clear_mirror_service`, `mirror_of_service`, `JoinTransfer`, `UnjoinTransfer`, the CLI. |
| 131 | §7.1 for category and transfer states (including the mirror refusal and the target refusals). §7.3 for transfers and mirrors. |
| 132 | Migration b (minus the use of `completion_entry_id`). The `remittance`/`unit` keys. The pending bucket. The import posts remittances. `list-pending-remittances`. **Added:** `classify-rules` applies remittance rules (§6.3), `reclassify` of a pending remittance (§7.1), and `split-line` refuses a remittance (§7.3). |
| 133 | `complete_remittance` outgoing, `set_completion_service`, `CompleteRemittance`, the CLI. **Added:** `reclassify` refuses a completed remittance. |
| 134 | The incoming completion, with the lot check (§9.4). |
| 135 | Migration c, `post_reversal`, the replay rule in `lots.py`, `entry_by_id_service`, `UncompleteRemittance` with the outgoing lot check, the CLI. |
| 136 | §18.6 to §18.8: the oracle comparison, the price guards for the three new modules, a crash test per writing command, and the five-way record distinction. |

### 16.2 Order

**Unchanged: 126 → 127 → … → 136.** The dependencies hold:

- 129 and 130 both need only 127;
- 131 needs `unabsorb` from 130;
- 132 needs only 126 and could start after it, but the spec puts transfers
  first;
- 135 needs 133 and 134.

No issue needs splitting. 127 is the largest, so its two-commit shape (the
moves, then the feature) keeps the review readable. A review stop after 131
(the transfer half complete) and after 136 fits the spec's "transfers land
first".

### 16.3 Changes to the issues' acceptance criteria

1. **126.** "Applying the rule file fails … when the counterpart is … the
   importing account itself" becomes "a transfer rule never matches a row
   imported into its own counterpart" (§17.1).
2. **127.** The testable "dated 2026-04-04 when Savings is imported first"
   needs a rule matching Savings' row too. The fixture uses one rule per side
   (§17.2).
3. **131.** "`split-line` is refused on … a pending remittance" moves to 132,
   because no remittance exists before 132.
4. **132.** Gains "`classify-rules` applies remittance rules to fall-through
   lines". The spec requires it (Requirements, "Rule priority … re-apply"),
   and no issue carries it.
5. **133.** Gains "`reclassify` and `split-line` refuse a completed
   remittance".
6. **134.** "A shortfall … fails … and writes nothing" is met by the
   in-transaction lot check (§9.4, §17.3).
7. **135.** Gains `journal_entries.reverses_entry_id` and the replay rule
   (§17.4), and "reversing an outgoing completion that would leave a later
   spend short fails and writes nothing".
8. **130.** Gains "joining refuses a line whose amount differs from the
   transfer's, or that goes the same way" (§17.6).

---

## 17. Gaps in the spec, and points for the user

1. **"The importing account itself" cannot be checked when the rule file is
   applied.**
   - A rule has no importing account; one rule file applies to every
     statement.
   - **Design:** a transfer or remittance rule never matches a row imported
     into its own counterpart, and evaluation moves on to the next rule
     (§3.4).
   - The alternative, failing the import naming the rule, would make the
     natural "my own name → Savings" rule unusable on Savings' statement.
2. **The 127 testable needs two rules.**
   - The move "carries the date of whichever side posted it". With one rule
     on Checking's row, Checking's row posts the move in both orders, dated
     2026-04-03.
   - It is dated 2026-04-04 only if Savings' row matches an inbound transfer
     rule (`transfer = "Checking"`).
   - The spec's "With a transfer rule" should read "with a transfer rule on
     each side". The balances agree either way.
3. **"A shortfall … fails … and writes nothing" (completion) is stronger than
   `multi-currency-and-fx`.**
   - There, a shortfall is a read-time failure: `record` accepts the entry and
     the reports fail.
   - **Design:** an incoming completion, and an outgoing reversal, replay the
     currency lots in their own transaction and refuse on a `LotError`. That
     reads lots, never prices. `record` is unchanged.
   - **Consequence:** on a ledger that already fails its replay, those two
     commands refuse with the existing failure.
4. **A wrong-Y reversal needs a ledger-level link.**
   - An ordinary mirrored entry would realise a spurious gain (incoming) or
     consume the oldest lot (outgoing) (§9.5).
   - **Design:** `journal_entries.reverses_entry_id`, and a rule in
     `lots.replay` that an entry and its reversal are as if neither existed.
   - This touches the core table and the replay, so it needs the user's
     explicit yes. It is also the primitive `undo-delete-edit` will want.
   - **Limit:** the securities fold would need the same rule before any
     security entry is ever reversed.
5. **Absorbed rows are posted, then cancelled** (§5.4).
   - "No expense, income or unclassified account holds any of it" holds for
     every balance and listing.
   - `entries-in-period` on the bucket and on B shows a net-zero pair per
     absorbed row. This is the price of every correction working unchanged on
     an un-absorbed row. **Confirm that this is acceptable.**
6. **`join-transfer` also refuses a different amount, or the same
   direction.** Joining them would leave the account off its statement.
   Different amounts are a spec Non-Goal.
7. **"Records … the direction".** The direction is derived from the line's
   sign (`statement_amount`), not stored, because the entry is immutable. The
   counterpart and the unit are stored.
8. **The unmirrored listing ignores transfers dated before the counterpart's
   first imported row** (minus the window). Without that bound, starting to
   import an account later lists its whole pre-import history for ever. This
   goes beyond the spec's "counterparts that have had a statement imported".
9. **`reclassify` onto an own account changes behaviour with no transfer
   rules at all.**
   - The spec mandates this. A ledger with no transfer rules where the user
     reclassifies onto an imported own account with an in-window fall-through
     now absorbs it.
   - So the no-regression goal ("rules have no transfer action") excludes
     `reclassify` onto own accounts, and the 136 oracle does not exercise it.
   - **New refusals on that path:**
     - the pending bucket;
     - the line's own statement account. That was a self-cancelling entry
       before.
10. **The same-date caveat is inherited.** A completion is dated at the
    original line but inserted later, so among same-date entries it replays
    last. An INR spend recorded on that same date before completing is
    replayed first. This is MC §13.1's "distinct dates only".
11. **Decisions the spec does not mention:**
    - `reclassify` refuses an absorbed mirror (unjoin first) and a completed
      remittance (uncomplete first);
    - `reclassify` of a pending remittance moves it out of the bucket;
    - `split-line` also refuses a completed remittance;
    - an unjoined row is marked `corrected`, so neither automatic absorption
      nor `classify-rules` touches it again;
    - a mirror un-absorbed because its transfer was reclassified keeps its
      `corrected` flag.
12. **`classify-rules` gives a transfer's mirror precedence over the
    mirror's own category rule** in the same run (§6.1). This is the
    in-run reading of "mirror recognition runs before any rule".
13. **The import count includes absorbed rows** (`N entries imported`). The
    count is pinned by tests, and absorption shows in the listings.
14. **Docs use new June statements** instead of extending `statement.csv`,
    so no existing checked example changes.
15. **`AGENTS.md`** should gain a sentence once this lands. The user edits
    it; this design does not. Proposed:

    > A classification's `kind` says whether a line is a category, a transfer
    > to an own account, the absorbed mirror of a transfer
    > (`mirror_of_entry_id`) or a remittance waiting in `Pending Remittances`
    > (`completion_entry_id` once completed). Mirror recognition runs in the
    > import's own transaction, before `match_rule`. An entry with
    > `reverses_entry_id`, and the entry it reverses, are skipped by the lot
    > replay.

---

## 18. Testing notes

The layers are the existing ones: pure tests, use cases against `session` /
`session_factory`, the CLI through `CliRunner`, docs examples, guards and
migrations. All data is fictional.

### 18.1 Pure (`tests/test_transfer_matching.py`)

- **`is_mirror`, as a table:**
  - days −4, −3, 0, +3, +4 (both 3s pass, both 4s fail);
  - an amount of 500.00 against 500.00000000 (passes) and against 500.01
    (fails);
  - the same sign (fails);
  - IBAN: both known and equal with spaces and lower case (passes), both known
    and different (fails), the source account has none (passes), the row has
    none (passes).
- **`nearest_transfer` / `nearest_row`:**
  - two 500 transfers in one week: the nearest wins;
  - equal distance: the earlier date wins, then the lower entry id;
  - nothing within the window gives `None`.
- **`match_rule`:**
  - a transfer rule whose account is `statement_account_id` is skipped and
    the next rule wins;
  - a category rule aimed at it is not skipped;
  - the four-argument call is unchanged.
- **The rule file:**
  - every §3.3 rejection, with its position and key;
  - round trip of the three kinds;
  - a category-only set renders byte-identically and keeps its `base`;
  - changing the kind or the unit gives one retired and one added.
- **`lots.replay`:**
  - a completion and its reversal leave lots, holdings and sales exactly as
    without them, in both directions;
  - the fold over the pair's costs nets to zero;
  - a ledger without `reverses_entry_id` gives identical output.

### 18.2 Import, end to end through `import-statement` with Deutsche Bank fixtures

- **The spec scenario** (−500.00 on 2026-04-03, +500.00 on 2026-04-04, a rule
  per side):
  - both orders give equal balances and one move, dated 04-03 or 04-04;
  - `list-unclassified` is empty;
  - every expense, income and unclassified balance is 0.
- **Re-import:** re-importing either statement writes nothing, and the
  `OperationGroup` count is unchanged.
- **The window:** a mirror 3 days after is absorbed; one 4 days after falls
  through and is listed.
- **Fall-through first:** Savings first with only Checking's rule. The move is
  posted and the fall-through cancelled in the same import and group.
- **A never-imported counterpart** (`Cash`): one move, nothing listed by
  `list-unmirrored-transfers`.
- **The record:** the mirror's classification is `kind = mirror`, names T, and
  has `proposed` on the bucket.
- **A crash:** monkeypatch `set_mirror_service` to fail on its call. The
  ledger snapshot and the group count are unchanged.

### 18.3 `classify-rules`

- **Both lines in the preview:** the transfer and its mirror, with the `kind`
  column.
- **No `kind` column** when every move is a category (the existing tests pin
  the header).
- **Precedence:** a mirror matched by a category rule is absorbed, not moved.
- **Symmetric rules:** the earlier candidate makes the move.
- **Lines left alone:** rule-classified and human-touched lines.
- **Remittance rules (132):** the pending bucket is created at apply, not at
  plan.
- **The existing fault test** still rolls back.
- **The guard:** an import between the preview and the apply that creates a
  mirror gives `ClassifyPlanChanged`.

### 18.4 Corrections

- **`reclassify` per §7.1's table, one test per cell.** The transfer →
  category case un-absorbs the mirror back to its bucket in one group.
- **The own-account path:** onto an own account with an in-window
  fall-through absorbs it. Onto the pending bucket, or onto the line's own
  account, is refused and writes nothing.
- **`join-transfer`:**
  - each refusal of §7.2;
  - a successful join of a late mirror (5 days);
  - `corrected = true`.
- **`unjoin-transfer`:**
  - the row is back in its bucket and listed;
  - the row is skipped by `classify-rules`;
  - a line that a rule first sent elsewhere returns to the bucket, not to
    that rule's account.
- **`split-line`:** refused per kind, with the reason in the message.

### 18.5 Remittances

- **Outgoing:** 1,012.00 EUR with Y = 90,000 gives a lot of exactly
  `Decimal("1012.00")`; the pending bucket is 0; `list-pending-remittances`
  is empty.
- **FIFO date:** a later-recorded INR spend dated after the remittance line
  but before the completion's recording consumes the lot.
- **Incoming:** with one 90,000 INR lot at 1,012.00, 1,100.00 completed with
  90,000 shows 88.00 under `INR` in `realised`.
- **Incoming shortfall:** `LotShortfall`, nothing written, no group.
- **`uncomplete-remittance`:**
  - incoming: the lot is back at 1,012.00 and `realised` is empty;
  - outgoing: the lot is gone, and redoing with 91,000 gives a lot at 1,012.00;
  - an outgoing reversal that starves a later INR spend is refused and writes
    nothing.
- **Refusals:** completing twice, completing a non-remittance, and
  uncompleting a pending remittance.
- **Net worth while pending:**
  - outgoing counts the euros once;
  - incoming nets Checking and Pending.

### 18.6 No regression (136)

- **An oracle captured as 126's first commit, from pre-feature code,** in
  `tests/pre_feature_baseline.py`'s style. The script:
  - two Deutsche Bank statements (Checking and Savings), both with a row to
    the other;
  - an `account = "Transfers"` clearing rule on each side;
  - both import orders;
  - `classify-rules`, `reclassify` onto an expense, `list-unclassified`,
    `balance`, `net-worth`, `list-rules`, `show-rules`, `list-accounts`,
    `list-operations` and `budget`.
- **What it may not include:** `reclassify` onto an own account (§17.9).
- **After 136:** byte-identical output.
- **The existing oracle:** `test_multi_currency_regression.py` must still pass
  unchanged.

### 18.7 Guards

- `tests/test_price_guards.py`: the three new modules are added to
  `_guarded_sources` and `RECORDING_MODULES`. The transitive-import test
  covers them.
- `tests/test_reader.py`: the four write commands are refused on a reader,
  and the two listings run there.

### 18.8 Migrations

For each of a, b and c: a round trip when empty, and a refusal with one
offending row that leaves the schema untouched. The CHECKs reject a mirror
without `mirror_of_entry_id` and a remittance without a unit (raw SQL insert).
`HEAD_REVISION` is pinned.
