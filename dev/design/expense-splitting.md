# Design: Expense splitting

Spec: `dev/specs/expense-splitting.md` (frozen)
Issues: `dev/issues/018`–`024`

Layering per `AGENTS.md` stays `app -> use_cases -> services ->
infrastructure/domain`. Only services touch a `Session`. Functions return
`Result[T, E]`; domain errors are `Exception` subclasses used as values.

---

## 1. Summary of the shape

| File | Change |
|---|---|
| `kohle/domain/models.py` | new `Split` and `SplitGroup` |
| `kohle/domain/domain_errors.py` | `SplitError` family, six union aliases, `ReclassifyError` gains `SplitError`, `NoClassificationForEntry.__str__` reworded |
| `kohle/services/split_services.py` | **new** — split upsert/lookup, group CRUD, splits-in-group query |
| `kohle/use_cases/journal.py` | `PEOPLE_ROOT`; `_aggregate_by_unit` → `aggregate_by_unit`; new `account_balance(ctx, …)` helper; `NetWorth` + `NetWorthReport` |
| `kohle/use_cases/splitting.py` | **new** — `PersonShare`, `SplitImportedEntry`, `UnsplitEntry`, `AddSplitGroup`, `WhoOwesWhat`, `SettleUp`, and the pure netting function |
| `kohle/use_cases/classification.py` | `Reclassify` refuses a split entry (§5.4) |
| `kohle/app/cli/cli.py` | `split-line`, `unsplit-line`, `add-group`, `who-owes-what`, `settle-up`, `net-worth`; an `entry_id` column on `entries-in-period` |
| `alembic/versions/` | **three** migrations, one per schema-bearing slice (§10) |
| `README.md` | the People branch, the six new commands |

**No new service for the reporting side.** Net worth and who-owes-what are
built entirely from `descendant_account_ids_service`, `account_lines_service`
and `list_accounts_service`, all of which exist. The only new service module
is for the two new tables.

One new use-case module, not three. `use_cases/` is one-module-per-noun
(`accounts`, `units`, `operations`, `journal`, `rules`, `classification`), and
splits, groups, person balances and settlement suggestions are one feature's
vocabulary: every one of them reads either the `splits`/`split_groups` tables
or the People branch. `NetWorth` is the exception and stays in `journal.py` —
see §9.1.

**Import direction is fixed by one constraint and is not negotiable:**
`splitting.py` imports `post_entry`, `aggregate_by_unit` and `account_balance`
from `journal.py`, and `classification_by_entry_service` from the *services*
layer. `classification.py` needs to know whether an entry is split (§5.4) and
reaches `split_by_entry_service` in the services layer directly — **not**
`splitting.py`, which would close a cycle, since `splitting.py` would then be
importing a module that imports it. This is the same shape the classification
design used to keep `journal.py` from importing `classification.py`.

---

## 2. The four questions the spec left open

### 2.1 The `People` root: a root account, `AccountType.asset`, no new marker

**Chosen: one account named `People`, `parent_id IS NULL`, `type = asset`,
seeded by migration. No new `AccountType`, no new `AccountKind`, no new
column.**

Placement first. `People` is a *root* — a sibling of `checking` and the
expense accounts, not a child of any of them. Issue 018 gives the reason and
it is a correctness argument, not a taxonomy preference: a parent's balance is
the sum of its children, so nesting `People` under an asset account would fold
"money someone owes me" into that account's rollup, and `balance Checking`
would start reporting money that is not in the bank.

Now the marker, which is the part worth arguing.

**The tree already is the marker.** Every consumer in this slice —
who-owes-what, settle-up, net worth's receivables section, the
person-account check in `split-line` — needs the *set of person account ids*,
and `descendant_account_ids_service(ctx, people.id)` returns exactly that set
with a query that already exists and is already tested for cycles and depth. A
type column would return the same set through a second query, and the two
could disagree: an account typed `person` living outside the branch, or an
`asset`-typed child inside it. Two encodings of one fact, with nothing keeping
them in agreement, is the thing to avoid.

**`AccountType` is the accounting-equation vocabulary, and a person is an
asset.** `asset` / `liability` / `income` / `expense` is what decides whether a
balance belongs on a balance sheet and with which sign. A person account is a
receivable when positive and a payable when negative, and it flips between the
two over the life of one account — Alice owes you after the dinner, you owe
Alice after the taxi. A fixed type column cannot express a value that changes
sign, whereas the *signed balance* already does, exactly as it does for an
overdrawn cash envelope. "Person" answers a different question — who the
counterparty is — and that question is answered by the branch.

**The cheap argument does not hold, so it is not used.** The obvious objection
to a new enum value is "that costs a migration". It does not:
`SqlEnum(AccountType)` is created with SQLAlchemy's default
`create_constraint=False`, so the live schema stores it as a bare
`type VARCHAR(9) NOT NULL` with no `CHECK` (verified against `kohle.db`).
Adding a value is a Python-only change. Recorded so the decision is not
re-litigated on a cost basis that is false — the case against rests on the two
modelling arguments above.

Two consequences, both stated because they look like oversights:

- **A person account is created with the existing `add-account` command.**
  `kohle-cli add-account Alice --type asset --parent People`. Issue 018's
  third criterion — "a person account can be created as a leaf under `People`
  and posted to like any other leaf account" — needs no code at all. An
  `add-person` command was considered and rejected: it is `add-account` with
  two arguments pre-filled, and it is the parallel structure this whole
  feature exists to avoid.
- **`--type` on a person account is very nearly cosmetic, and that is
  deliberate.** Net worth defines its receivables section as *the People
  subtree*, not as *accounts typed asset*, so a person account created with
  the command's default (`expense`) still counts as a receivable and still
  appears in who-owes-what. `asset` remains the right value and the README
  says so, but nothing in this slice validates it. A check that a child of
  `People` must be typed `asset` would be a rule whose only effect is to
  reject input that already behaves correctly.

**Posting directly to `People` is prevented by the existing leaf-only rule**
as soon as it has one child, and before that it is the same "stranded
postings" gap the ledger already has for every other account
(`cli-record-and-balances.md` §4). No new check.

### 2.2 Group/trip data model: a standalone `split_groups` table, referenced from `splits`

**Chosen: `split_groups(id, name UNIQUE)` plus a nullable `splits.group_id`.**

The candidates, and why each other one loses:

- **A free-text label column on `journal_entries`.** Cheapest — no table, no
  join. Rejected because a typed label has no referent: `"Italy trip"` and
  `"Italy Trip"` silently become two groups, there is no way to list what
  groups exist so no way to discover the right spelling, and there is no way
  to rename one. Every other first-class noun in this codebase (accounts,
  units, rules) is a row with a unique name and CLI verbs; a string column
  would be the parallel structure.
- **An attribute on `OperationGroup`.** Rejected on layering: `OperationGroup`
  is the audit trail of one use-case *run*, created lazily by
  `DbTransactionContext.record_transaction_step` and never a domain concept.
  Editing a split posts more entries in a new operation group, so a trip would
  fragment across groups within a week of use, and the audit trail would
  acquire a domain meaning it must not have.
- **`group_id` on the adjusting entry** rather than on the split. Rejected
  because the adjusting entry is replaced on every edit (§5.3), so the group
  tag would have to be copied forward by hand on each correction and would be
  lost the moment someone forgot. The group is a property of *the split* — the
  fact that this dinner belongs to the Italy trip — and survives any number of
  corrections to how it was divided.

`split_groups` is deliberately thin: `id`, `name` with
`UniqueConstraint("name")`, and `Archivable` for consistency with every other
table. No date range, no member list, no owner. A trip's date range is
derivable from its splits' entries and nothing in the spec asks for it.

**Groups are created explicitly (`add-group NAME`) and looked up strictly.**
`split-line --group "Itlay trip"` fails with `SplitGroupNotFound`; it does not
create a second group. This is the codebase's existing rule that user-typed
names resolve strictly and never auto-vivify — the rule that makes a typo in
`--from` an error rather than a new account. Auto-creating on first use was
considered, on the grounds that a trip group is created exactly once and a
second command is friction; rejected because the failure it introduces is
silent (a misspelled group holds one split and the rest go elsewhere) and the
one it prevents is a single extra command per trip. The auto-created
unclassified buckets are not a counter-example: their names are module
constants the user never types.

**No `list-groups` command.** `who-owes-what --by-group` enumerates every
group, including one with no splits yet (§7.2), so a separate listing would
print a strict subset of what a command in the same slice already prints.

### 2.3 Debt simplification: global balances always; `--group` filters *who*, not *what*

**Chosen: `settle-up` runs over live person-account balances, globally.
`settle-up --group "Italy trip"` restricts the set of *people* to those who
appear in that group's splits, but still uses their full current balances.**

The issue text allows either scope, and the deciding argument is issue 023's
last criterion: *executing a suggested transfer and re-running the report
confirms the involved balances have zeroed out.* That criterion is only
satisfiable against balances that settlement actually moves.

A group's numbers are not such balances. A group aggregates its member
splits; settling up with Alice is an ordinary transfer (`record 48 --from
Alice --to Checking`), and an ordinary transfer belongs to no group — the spec
closes that door itself by making settlement "no new mechanism needed", and
`record` has no `--group` flag. So a group total never decreases when a debt
is paid. Computing min-cash-flow over group totals would therefore suggest
transfers for debts that are already settled: a suggestion that is not merely
imprecise but actively wrong, and wrong in a way that re-running the report
does not reveal.

Making settlement transfers group-taggable would fix that, and is rejected: it
means a `record` variant that knows about groups, which is the "new mechanism
for settling" the spec's Non-Goals explicitly close.

Hence the split of responsibilities, which is the part to keep straight:

> **A group total is a historical allocation — what this trip cost each
> person. A person-account balance is a live debt — what they owe you now.
> Only the second is settleable, and `settle-up` only ever reads the second.**

`--group` remains useful and is what the user actually asked for: *settle up
with everyone from the Italy trip.* Restricting the participant set while
keeping real balances gives an answer that is both scoped and executable. The
cost, stated: if Alice also owes you for something unrelated,
`settle-up --group "Italy trip"` settles that too. The report prints the
balances it is working from, so this is visible rather than hidden, and it is
the right answer anyway — you do not make two transfers with one person.

**The user is a participant in the netting, and that is what makes
simplification possible at all.** This is worth spelling out because the
ledger's shape hides it. Kohle records only the user's bilateral position with
each person — there is no Alice-owes-Bob edge anywhere in the schema — so the
debt graph is a star with the user at the centre, and in a star the minimum
number of settling transfers is trivially one per non-zero person. Nothing to
simplify.

The simplification appears when the user is treated as one node among the
others, with position

```
position[you] = -sum(position[p] for p in people considered)
```

which is exact by construction, since the user is the counterparty of every
person balance. Netting over `people + {you}` then produces person-to-person
transfers that route the user out of the middle. Alice owes you €50 and you
owe Bob €50 becomes **one** suggested transfer, Alice pays Bob €50 — issue
023's acceptance test, and the whole point of the feature.

Such a transfer is executable with the existing entry model, which is the
other half of issue 023's criterion: `record 50 --from Alice --to Bob` credits
Alice (she no longer owes you) and debits Bob (you no longer owe him),
balances, and lands on two leaves. Nothing new.

### 2.4 Net worth: one figure, with receivables as a visible line inside it

**Chosen: a single net-worth total that includes receivables, presented over a
breakdown that shows the receivables contribution as its own line.** Both, not
either.

Issue 024's operative requirement is that the person-account balances are
"visibly included in the reported output, not silently dropped". A single bare
number fails that test on its own terms: from `Net worth: 4,812.00` the user
cannot tell whether receivables were counted, double-counted, or forgotten,
which is exactly the failure the criterion names. Two independent numbers with
no total fail the spec's requirement that receivables *count* toward net
worth — the user would be adding them up by hand.

The breakdown makes the claim checkable and the total makes it a net-worth
figure:

```
section                   unit    quantity   at cost
------------------------  ------  ---------  --------
Own accounts              EUR      4796.00    4796.00
Receivables (People)      EUR        16.00      16.00
Net worth (at cost)                           4812.00
```

Rejected: a separate `receivables` subtotal presented *alongside* net worth
rather than inside it, on the "different liquidity, different collectability"
argument. That argument is real — money owed is not money held — but it is an
argument for showing the line, which this design does, not for excluding it
from the total, which the spec forbids.

§9 covers what "at cost" means and why the total is computed the way it is.

---

## 3. Issue 018 — the People branch

### 3.1 The seeded root

```python
PEOPLE_ROOT = "People"    # kohle/use_cases/journal.py, beside BASE_CURRENCY
```

In `journal.py` rather than in `splitting.py` because it is a ledger constant
of the same kind as `BASE_CURRENCY` and `UNCLASSIFIED_EXPENSE`, and because
`NetWorth` (which lives in `journal.py`, §9.1) needs it — putting it in
`splitting.py` would make `journal.py` import from `splitting.py` and close
the cycle §1 forbids.

The row is inserted by migration (§10.1), not by a get-or-create at first use.
Issue 018 asks for a migration, and the two paths differ in a way that
matters: the unclassified buckets are created on the first import through
`_get_or_create_account` and therefore carry `Operation` rows, whereas the
People root is part of the shape of the ledger, like a table. A root account
that appears the first time somebody happens to split something would make
`list-accounts` on a fresh install incomplete, and issue 018's last criterion
is that `People` shows up as a distinct top-level branch — which has to be
true before any split exists.

**Consequence, stated because it is a genuine exception:** the seeded row has
no `Operation` and belongs to no `OperationGroup`. Every other `Account` row
in the database was created through `crud_create` and is in the audit trail.
The justification is that this one was not a user action; it shipped with the
schema. `list-operations` will show a `People` account that no group created,
and that is the honest record.

### 3.2 Tests do not get the seeded row

`tests/conftest.py` builds the schema with `base.metadata.create_all`, not by
running Alembic. **The migration's seed row therefore does not exist in any
test**, and every test that touches the People branch has to create it. This
is a trap with a silent failure mode — `AccountNotFoundError("People")` from a
use case that looks like it should have worked — so it gets a `people_root`
fixture in `conftest.py` rather than a repeated three lines, and this
paragraph exists so the failure is recognised the first time it is seen.

### 3.3 Absence of the root is an error, not emptiness

`WhoOwesWhat`, `SettleUp` and `NetWorth` resolve `People` with the strict
`get_account_by_name_service` and propagate `AccountNotFoundError`.

This is deliberately *unlike* `ListUnclassified`, which swallows the same
error into an empty list (classification design §6.2). The difference is what
the condition means at each call site. A missing unclassified bucket means
nothing has been imported yet — a normal state of a new ledger. A missing
`People` root means the database is behind its migrations, which is a broken
installation, and reporting a net worth of zero receivables for it would be
answering a question the ledger cannot currently answer. A fresh, fully
migrated ledger that has simply never split anything has the root, with no
children, and reports an empty receivables section — which is the emptiness
case, handled correctly without swallowing anything.

---

## 4. Issue 019 — splitting an already-imported line

### 4.1 The command

```
kohle-cli split-line ENTRY_ID --mine QUANTITY --share PERSON:QUANTITY [--share ...] [--group NAME]
```

```
kohle-cli split-line 42 --mine 32 --share Alice:48 --group "Italy trip"
```

`--share` uses the colon-separated `NAME:VALUE` shape `record-split --line`
established, and colons are safe for the same reason they are there: account
names carry spaces but not colons. `--share` is `multiple=True,
required=True`, so Click rejects a share-less invocation with
`Error: Missing option '--share'` (verified, Click 8.3.1) and no domain error
is needed for the empty case.

**`--mine` is required, and it is required because of what it buys.** Issue
019's last criterion is that split amounts which do not sum to the line's
value produce a clear error. If `--mine` defaulted to the remainder, the sum
would be correct by construction and that criterion would be unfalsifiable —
the same objection this project's previous design raised against substring
rule patterns, which satisfied "malformed patterns are rejected at creation"
only vacuously. Stating your own share makes the command a statement of the
whole allocation, and the check then catches the arithmetic mistake it exists
to catch. `--mine 0` is legal and means you paid entirely for someone else.

**Shares are quantities in the original line's unit, at the original line's
price.** Not values. For a base-currency line `unit_price` is 1 so quantity
and value coincide, which is why `--mine 32 --share Alice:48` on an €80 line
reads as euros; for any other unit, splitting by quantity is the only reading
that keeps the spec's currency-mismatch rule true — *the split's lines use the
original transaction's recorded quantity, unit, and price exactly*. The sum
check is therefore on quantity:

```
own + sum(shares) == original_line.quantity     else SplitDoesNotSumToLine
```

**`entries-in-period` gains an `entry_id` column.** `split-line` takes an
entry id and no read command currently prints one except
`list-unclassified`, which by definition does not show lines that were
classified successfully — so the ids of exactly the lines a user most wants to
split are unreachable without opening the database. One dict key;
`line.entry.id` is already loaded by the existing `joinedload`. This is the
same principle that made `list-rules` print the id `remove-rule` takes.

### 4.2 Finding the line, by reusing the classification record

`SplitImportedEntry` does not ask the user which account to split away from.
It reads the entry's `Classification`:

```
classification   = classification_by_entry_service(ctx, entry_id)
original_line    = the line of the entry whose account_id == classification.proposed_account_id
current_account  = classification.final_account_id
```

The two handles are the same two the `Reclassify` precedent uses and they are
easy to get backwards:

- **The line whose shape is copied is located by `proposed_account_id`** — the
  original entry always carries its counterpart line on the proposed account,
  even after a correction moved the value elsewhere. Its `unit_id`,
  `unit_price`, `quantity` and `is_debit` are what the split's lines are built
  from.
- **The account the value is taken out of is `final_account_id`** — where the
  money sits *now*. Splitting a line that was reclassified from
  `Unclassified Expense` to `Eating out` must take the shares out of
  `Eating out`, not out of the bucket a second time.

Two things fall out of using the classification row, and both are wanted:

- **Only imported lines can be split**, since only imported lines have a
  classification. That is precisely the spec's scope — the retroactive split
  of an *imported* line — and a from-scratch split is `record-split`, which
  the spec's Non-Goals keep. The error is the existing
  `NoClassificationForEntry`, reused rather than twinned. Its message is
  reworded from "has no classification to correct" to *"Journal entry id N has
  no classification record; only imported lines can be reclassified or
  split"*, because it now has two callers. `tests/test_reclassify.py` asserts
  on the type, not the string, so nothing breaks.
- **Split composes correctly with reclassify in one direction and is refused
  in the other** — §5.4.

### 4.3 The adjusting entry

One entry, dated the original entry's date, reference `uuid4().hex`,
description `f"Split: {entry.description}"`:

```
lines = [ LineSpec(current_account, unit, original.quantity, price, is_debit = not original.is_debit),   # reverse
          LineSpec(current_account, unit, own,               price, is_debit = original.is_debit),       # re-post own
          LineSpec(person_i,        unit, share_i,           price, is_debit = original.is_debit) ... ]  # re-post shares
```

posted through `post_entry`, which is the spec's requirement and needs no
change to `post_entry` at all.

**It mirrors the original line's side instead of branching on expense vs
income**, exactly as `Reclassify` does, and the walk-through is worth doing
because the income case is the one that looks wrong until you check it. An
expense import debits the expense account; the split credits it for the full
amount, debits it back the own share, and debits each person — leaving €32 on
`Eating out` and a €48 receivable on `People:Alice`, which is issue 019's
acceptance test. An income import credits the income account; the split debits
it for the full amount, credits back the own share, and *credits* each person
— giving the person a **negative** balance, meaning you are holding money that
is theirs. Both are right, from one expression.

**Why the full reverse-and-re-post and not the two-line shift** (`credit
Eating out 48, debit Alice 48`), which produces identical balances with one
fewer line. Three reasons, in order of weight. Issue 019's criterion says the
split posts "as a reversing-and-re-posting adjusting entry", and a shift does
not re-post. The full entry is *self-describing*: it states the entire
allocation (80 = 32 + 48) in one place, so undo is a pure mirror of its lines
(§5.1) and the group report can read allocations off the entries without
consulting the originals. And it keeps `--mine` load-bearing — under the shift
shape the own share would be a validation-only argument, which is the kind of
parameter that later gets "simplified" away.

The accepted cost: the entry touches `current_account` twice, once on each
side, so `entries-in-period Eating out` shows two rows for it. That is legal
(`uq_journal_line_entry_account_unit_side` includes `is_debit`) and it is
truthful — `cli-record-and-balances.md` §5.2 already recorded that reversing
entries legitimately touch one account twice.

**The own-share line is omitted when `--mine` is 0.** A zero-quantity line
carries no information and `--mine 0` is a legitimate case (you paid entirely
for someone else). One conditional, stated so it is not mistaken for a bug.

**Two persons named twice in one invocation** (`--share Alice:20 --share
Alice:28`) violates `uq_journal_line_entry_account_unit_side` and surfaces as
the existing `DuplicateLineInEntry` — *"Two lines on the same account, unit and
side; combine them"* — which is already the actionable message. No pre-check;
the same reasoning `cli-record-and-balances.md` §5.3 gave.

### 4.4 The `splits` record

```python
class Split(base, Archivable):
    __tablename__ = "splits"

    id:                 Mapped[int]        = mapped_column(Integer, primary_key=True)
    journal_entry_id:   Mapped[int]        = mapped_column(ForeignKey("journal_entries.id"), nullable=False)
    adjusting_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id"), nullable=True)
    group_id:           Mapped[int | None] = mapped_column(ForeignKey("split_groups.id"), nullable=True)   # issue 021

    entry:           Mapped["JournalEntry"]      = relationship("JournalEntry", foreign_keys=[journal_entry_id])
    adjusting_entry: Mapped["JournalEntry|None"] = relationship("JournalEntry", foreign_keys=[adjusting_entry_id])
    group:           Mapped["SplitGroup | None"] = relationship("SplitGroup")

    __table_args__ = (
        UniqueConstraint("journal_entry_id", name="uq_split_journal_entry"),
    )
```

This is the `Classification` shape, for the same reason: **the unique
constraint on `journal_entry_id` is what makes "the split of this line" a
phrase with one referent**, which is what undo and edit need something to
point at, and it is what keeps every read free of a max-per-entry subquery.

`adjusting_entry_id` is the *current* effecting entry, and it is the whole
record. It is nullable because undo (§5.1) sets it to `NULL`: after an undo
the split has a history but no current allocation. Explicit `foreign_keys=` on
both entry relationships because they point at the same table; SQLAlchemy
cannot infer the join otherwise.

**Why nothing about the shares is stored.** The obvious columns —
`own_share`, a `split_shares` child table of `(person_account_id, quantity)` —
are not here because the adjusting entry's lines already *are* the shares, and
they are the copy the ledger actually acts on. Storing them twice creates a
pair that can disagree, with the stored copy being the one nothing validates.
Everything undo, edit and the group report need is read off
`adjusting_entry.lines`.

**Undo sets `adjusting_entry_id = NULL`; it does not delete or soft-delete the
row.** A soft delete would leave the row in the table and
`UniqueConstraint(journal_entry_id)` would then block re-splitting the same
line — the exact problem that made `rules` deliberately unconstrained. An
update keeps one row per entry forever and keeps the referent single, which is
the `Classification.final_account_id` precedent, audited the same way through
`crud_update`.

`Archivable` for consistency with every other table. As with
`classifications`, `deleted_at` is never written for `splits` and must not be.

### 4.5 Errors

`SplitImportedEntry.execute(entry_id, own_share, shares, group_name)`:

| condition | error |
|---|---|
| unknown or unimported entry | `NoClassificationForEntry` (reused, §4.2) |
| unknown person account | `AccountNotFoundError` (reused) |
| named account is not under `People` | `NotAPersonAccount(name)` |
| shares do not sum to the line | `SplitDoesNotSumToLine(line_quantity, given)` |
| unknown group | `SplitGroupNotFound(name)` |
| person account has children | `PostingToNonLeafAccount`, from `validate_lines` |

All reach the user through the CLI's existing
`raise click.ClickException(str(err))`, which is issue 019's "clear error, not
a traceback" with no new CLI work.

The person-account membership check resolves each name strictly, then tests
membership in `descendant_account_ids_service(ctx, people.id)`. One CTE call
for the whole invocation, not one per person.

### 4.6 What traceability actually means here

Issue 019 asks that both the reversal and the re-post be "traceable via
`Operation` rows back to the original import". Precisely:

- The `Operation` rows say **what was written** — one `OperationGroup` per
  `split-line` run holding the adjusting entry's `create` and the `splits`
  row's `create` or `update`, plus the reversal entry's `create` on an edit.
- The `splits` row says **what it refers to** — `journal_entry_id` is the
  foreign key back to the imported entry, and `adjusting_entry_id` is the
  forward key to the entry that effects the split.

Neither alone is the trace; the pair is. This is stated because `Operation`
carries only `entity_type`/`entity_id`/`action` and does not and will not
carry a link between two entities — `Operation.field` and `Operation.state`
remain unwritten for the reason the classification design gave.

---

## 5. Issue 020 — undoing and editing a split

### 5.1 Undo is a mirror of the current adjusting entry

```
kohle-cli unsplit-line ENTRY_ID
```

`UnsplitEntry` loads the split, and posts one entry whose lines are the
current adjusting entry's lines with `is_debit` flipped — same accounts, same
units, same quantities, same prices, opposite sides. Dated the original
entry's date, described `f"Unsplit: {entry.description}"`. Then
`set_split_adjusting_entry_service(ctx, split.id, None, group_id)` through
`crud_update`.

Because the split entry states the complete allocation, mirroring it restores
the pre-split state exactly with no arithmetic: the expense account goes back
to the full original amount and the person accounts go back to zero for that
line, which is issue 020's third criterion discharged structurally rather than
by computation.

Unknown split reference → `NoSplitForEntry(entry_id)`, issue 020's last
criterion. An entry that was split and then undone is in the same position: it
has a `splits` row with `adjusting_entry_id IS NULL`, and `unsplit-line` on it
returns `NoSplitForEntry` as well, because there is no current split to undo.

### 5.2 The `splits` row is read through the not-found error

`split_by_entry_service(ctx, entry_id) -> Result[Split, SplitError]` returns
`NoSplitForEntry` when there is no row. Two of its three callers treat that
error as "there is no split", the way `ListUnclassified` deliberately swallows
`AccountNotFoundError` for a missing bucket.

Rejected: `Result[Option[Split], SplitError]`. `kohle/core/option.py` exists
but is used only by the unwired TUI and by no service anywhere; introducing it
here would make this the one service in the codebase that reports absence
differently from the other dozen, for a gain of one `isinstance` check at two
call sites.

### 5.3 Edit is undo-then-split, in one transaction, and it must be two entries

Re-running `split-line` on an already-split entry replaces the allocation:
`SplitImportedEntry` posts the mirror of the existing adjusting entry
(exactly what `UnsplitEntry` posts), then posts the new split entry, then
points the `splits` row at the new one. Both entries and the row update land
in one `DbTransaction`, hence one `OperationGroup`, so a failure anywhere
leaves the previous split intact.

**These cannot be folded into a single entry, and someone will try.** The
combined entry would carry two credit lines on the same expense account — the
reversal of the old allocation and the reversal inside the new one — which
violates `uq_journal_line_entry_account_unit_side` and fails with
`DuplicateLineInEntry`. The constraint, not taste, fixes this at two entries.

After editing 32/48 to 40/40 the full history is three entries — the import,
the first split, the correction pair — all readable through `entries-in-period`
and `list-operations`, which is issue 020's fourth criterion.

**Replacement is not gated behind a flag.** `split-line` on an already-split
entry does not require `--replace` and does not refuse. It is one transaction,
it is append-only, it is reversible, and the command reports what it did
(`Replaced the previous split of entry 42`). Requiring `unsplit-line` first
would be two commands for one intent, with an ordering the user has to know.
Recorded because "silently changes an existing allocation" is a fair
objection, answered by the output line rather than by a flag.

**`--group` is authoritative on every run.** Re-splitting without `--group`
clears the group; re-splitting with a different one moves it. A flag whose
absence means "keep whatever was there" is invisible state, and the alternative
reading — absence means no group — is the one the user can see in the command
they typed.

### 5.4 `Reclassify` refuses a split entry

This is the one change to existing behaviour, it is not asked for by any
issue, and without it this slice ships a silent ledger corruption.

`Reclassify` reverses the *original line's full quantity* out of
`final_account_id`. On a line that has been split, that account no longer
holds the full quantity — it holds the own share — so reclassifying an €80
dinner split 32/48 would leave `Eating out` at **−48**, `Restaurants` at 80 and
Alice at 48. It balances, `validate_lines` passes, and it commits.

`Reclassify` therefore calls `split_by_entry_service` first and returns
`EntryAlreadySplit(entry_id)` when a current split exists — *"Journal entry id
42 is split; undo the split with `unsplit-line 42`, reclassify, then split
again"*. The fix names the two commands, both of which exist.

**Rejected: making `Reclassify` split-aware** — reversing only the remaining
own share, which is the arithmetically correct adjusting entry. It requires
`classification.py` to know the split's shares, and `splitting.py` already
reads the classification, so the two use-case modules would import each other.
Reaching for `split_services` from `classification.py` avoids the cycle for the
*guard* (a service call, no use-case import), but a correct re-post would need
the split's line detail and the branch logic to go with it — real coupling
between two corrections that are otherwise independent. Refusing converts a
silent wrong balance into a two-command detour.

**The other order needs nothing**: reclassify first, then split, works because
`SplitImportedEntry` takes its shares out of `final_account_id` (§4.2).

**Splitting does not touch the `Classification` row.** `final_account_id` still
names the account holding the own share, `corrected` is unchanged, and the line
stays out of `list-unclassified` if it was already out of it. A split is not a
classification decision and must not be recorded as one, or the labelled
dataset the classification slice exists to accumulate starts carrying rows
where the human "corrected" nothing.

---

## 6. Issue 021 — groups

```python
class SplitGroup(base, Archivable):
    __tablename__ = "split_groups"

    id:   Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (UniqueConstraint("name", name="uq_split_group_name"),)
```

```
kohle-cli add-group "Italy trip"
```

`AddSplitGroup.execute(name)` strips the name, rejects empty
(`EmptySplitGroupName` — matching `EmptyAccountName` and `EmptyRulePattern`),
and maps the unique violation to `DuplicateSplitGroup(name)` in the service,
the same shape `add_account_service` uses for `accounts.name`.

`splits_in_group_service(ctx, group_id)` returns the group's `Split` rows with
`selectinload(Split.adjusting_entry).selectinload(JournalEntry.lines)` and
`joinedload` on the line accounts — everything the group report reads, loaded
before the session closes.

**A group's per-person effect is computed from the *current* adjusting entries
only.** For each split in the group with a non-`NULL` `adjusting_entry_id`,
sum the lines that land on person accounts. Reversal entries from past edits
are not in the group's set and do not need to be: they are only ever paired
with the entry they reverse, and that entry is no longer any split's current
one. A split that has been undone contributes nothing, correctly.

Issue 021's remaining criteria are structural: `group_id` is nullable so a
split created without `--group` behaves exactly as before, and a group is
queried for its member splits by the one foreign key.

---

## 7. Issue 022 — who-owes-what

```
kohle-cli who-owes-what [--by-group]
```

### 7.1 The global view

```python
@dataclass(frozen=True, slots=True)
class PersonBalance:
    person_name: str
    balances: list[UnitBalance]
```

`WhoOwesWhat` resolves the `People` root, lists its children with
`list_child_accounts_service`, and calls `account_balance(ctx, person.id)`
for each — the `ctx`-taking helper factored out of `QueryAccountBalance`
(§9.2). Per-person, not per-branch, so the answer is the same one
`balance Alice` gives.

**Every person account is listed, including those with no lines at all.** That
is what makes issue 022's last criterion true: a settled person has a
`UnitBalance` with `quantity == 0` and renders `EUR 0.00`, because their
account has lines that cancel; a person never split against has an **empty**
`balances` list and renders `—`. The distinction falls out of the data instead
of needing a flag, and it only works because the listing is driven by the
account tree rather than by the lines.

Balances are reported **per unit**, like `balance`. In practice there is one
unit: every split descends from an imported line, and `ImportStatement` posts
base currency at price 1. A person account can hold something else only via
`record-split`, and reporting per unit means that holding is shown rather than
silently folded into a euro total.

`UnitBalance` is reused rather than twinned. It is already the detached
per-unit value type, already the contract `balance` renders, and a
`PersonUnitBalance` with identical fields would be a second name for one shape.

### 7.2 The per-group view

`--by-group` renders one block per group — every group, including one with no
splits, so the report doubles as the group listing (§2.2) — with the same
`PersonBalance` shape inside:

```python
@dataclass(frozen=True, slots=True)
class GroupAllocation:
    group_name: str
    allocations: list[PersonBalance]
```

Splits with no group do not appear in any block and are unaffected in the
global view, which is issue 022's third criterion.

**The column is labelled `from splits`, not `balance`, and the block carries a
one-line note that group figures are not settlement-adjusted.** §2.3 is the
reason: these two numbers answer different questions and will be read side by
side. Labelling them identically is how a user concludes that a paid-off trip
debt is still outstanding.

---

## 8. Issue 023 — settle-up

```
kohle-cli settle-up [--group NAME]
```

### 8.1 The pure netting function

```python
@dataclass(frozen=True, slots=True)
class SuggestedTransfer:
    payer: str | None      # None is you
    payee: str | None      # None is you
    unit_identifier: str
    quantity: Decimal


def settle(positions: Mapping[str | None, Decimal]) -> list[tuple[str | None, str | None, Decimal]]
```

Pure and DB-free, unit-testable without a fixture — the treatment `match_rule`
and `aggregate_by_unit` already get, for the same reason: every decision in
this section lives in it and none of them needs a session.

`positions` maps participant to the net amount they must pay out, which for a
person is exactly their account balance (positive means they owe you, so they
pay) and for the user is the negation of the sum (§2.3). **The input therefore
sums to exactly zero by construction**, which is what guarantees the loop
terminates with every participant at zero rather than at a residue.

The algorithm is greedy max-payer / max-receiver: repeatedly take the largest
positive and the largest negative position, emit a transfer of
`min(payer, -receiver)`, subtract, drop anyone who reaches zero. At most
`n - 1` transfers for `n` participants.

**Ties break on a total order.** The selection key is `(-amount, name or "")`,
so two participants with equal amounts always resolve the same way and the
same ledger always produces the same suggestion. `None` (you) cannot be
compared against a `str`, hence `name or ""`, which also means you are picked
first on a tie — arbitrary but fixed. This is the same reasoning that made the
rule tie-break `id` rather than insertion order: deterministic has to be a
property of the comparison, not of what the container happened to return.

**"Minimum" is the greedy minimum, and the honest statement is that the exact
minimum is NP-hard.** Finding the fewest transfers means partitioning the
participants into the largest number of subsets that each sum to zero, which
is the subset-sum partition problem. Greedy is optimal whenever no proper
subset of participants sums to zero — which covers the spec's acceptance test
and essentially every real settlement — and produces at most `n - 1` transfers
otherwise, against the `n` of naive pairing. For the five-or-so people a
personal ledger tracks an exact search would be affordable, and it is not
built: it would be a second algorithm with a different answer only in cases
nobody can construct by accident, and the spec's own test is the greedy result.
Recorded so the gap is known rather than discovered.

### 8.2 Scope and per-unit netting

Netting runs **once per unit**, over the participants holding that unit. You
cannot net euros against shares, and quantizing across units would need
prices, which the ledger does not have at posting time and will not have
before the price feed. In practice there is one unit and this degenerates to
the simple case; it is written per-unit because the alternative is silently
dropping a non-euro person balance from the suggestions.

`--group NAME` restricts the participant set to the people appearing in that
group's current splits, keeps their full balances, and recomputes your
position as the negation of that subset's sum (§2.3).

**Nothing is stored.** `SettleUp` is a read: it resolves accounts, aggregates
lines, and returns values. It writes no rows and therefore — since issue 011
made `OperationGroup` creation lazy — leaves no group behind, which is issue
023's third criterion.

### 8.3 Output

A table of `payer`, `payee`, `unit`, `quantity`, with `you` rendered for
`None` and a trailing line naming the `record` invocation shape:

```
payer   payee   unit   quantity
------  ------  -----  --------
Alice   Bob     EUR       50.00

Settle with: kohle-cli record <date> "<description>" 50 --from Alice --to Bob
```

The user supplies their own cash account for any transfer involving them,
because the command has no way to know which one and inventing a
"default cash account" setting would be a configuration mechanism this
codebase does not have. `No transfers needed` on an empty result, matching the
`No rules` / `No holdings` house style.

---

## 9. Issue 024 — net worth

```
kohle-cli net-worth
```

### 9.1 Where it lives, and what it deliberately is not

`NetWorth` goes in `use_cases/journal.py`, beside `QueryAccountBalance`. It is
a balance rollup over a set of account ids and it reuses that file's private
fold; `cli-record-and-balances.md` §1 argued against a `reporting.py` on the
grounds that it would scatter reads across two files, and that argument has not
changed. The stated trigger for splitting `journal.py` remains FIFO lots from
`portfolio-and-profit-reporting.md`, and net worth should move with
`QueryAccountBalance` when it does.

**This lands a piece of a deferred spec, and the boundary is drawn
explicitly.** `cli-record-and-balances.md` puts "net worth or any cross-unit
valuation total" in its Non-Goals, deferred until a price feed exists, and
`portfolio-and-profit-reporting.md` still owns that work. What issue 024 needs
is not market valuation — it is that person-account balances count. So this
slice builds **net worth at recorded cost**, which needs no price source at
all, and leaves market valuation where it is.

### 9.2 The computation

```
people_ids = descendant_account_ids_service(ctx, people.id)
balance_sheet_ids = { a.id for a in list_accounts_service(ctx)
                      if a.type in (asset, liability) } | people_ids

own         = aggregate_by_unit(account_lines_service(ctx, balance_sheet_ids - people_ids))
receivables = aggregate_by_unit(account_lines_service(ctx, people_ids))
```

Three things in that are decisions:

**Income and expense accounts are excluded, and the reason is not taxonomy.**
Every entry balances, so the signed sum over *all* accounts is identically
zero — a net worth that included flow accounts would always report 0.00 and
would look like a bug in the fold rather than a definition error.

**Receivables are defined as the People subtree, unioned in rather than
selected by type.** This is the definition from §2.1 — the People branch is
part of net worth because of where it sits — and it has the practical effect
that a person account created with `add-account`'s default `expense` type
still counts. Partitioning is by subtree membership, so nothing is
double-counted.

**Liabilities need no sign handling.** A credit-normal account accumulates
credits, and the fold subtracts them, so a liability arrives negative and adds
negatively. The same mechanism gives issue 024's third criterion for free: a
person with a positive balance raises net worth, a person you owe (negative)
lowers it. No branch on `AccountType` anywhere in the computation.

### 9.3 Valuing at cost — and the trap in the obvious formula

```python
@dataclass(frozen=True, slots=True)
class NetWorthReport:
    own: list[UnitBalance]
    receivables: list[UnitBalance]

    @property
    def own_at_cost(self) -> Decimal: ...
    @property
    def receivables_at_cost(self) -> Decimal: ...
    @property
    def net_worth_at_cost(self) -> Decimal: ...   # own + receivables
```

Each total is `sum(b.quantity * b.average_cost)` over the section's unit
balances, treating a `None` average cost as a zero contribution — `average_cost`
is `None` only when `quantity` is 0, so the contribution is 0 either way. The
properties live on the use-case value type, not in the CLI: unlike the
base-currency restatement row that `balance` adds in the CLI, this is a number
nothing else computes.

**It must be `quantity × average_cost` and not `sum(line.value)`, and the two
differ.** `JournalLine.value` is a base-currency amount by construction
(`unit_price` is what one unit cost in base currency), so summing signed line
values looks like a shorter route to the same answer. It is not:

> Buy 10 @ 100, then sell 5 @ 130, starting from zero cash.
>
> - Signed line values: Broker `1000 − 650 = 350`, Checking `−1000 + 650 =
>   −350`. **Total 0.** The ledger claims nothing happened.
> - Moving-average fold: Broker quantity 5, average cost 100 → **500** at cost;
>   Checking −350. **Total 150** — the realised gain.

The reason is that `record` derives the counter-side of a sale as
`quantity × price` in base currency and posts no gain to an income account, so
the sale's two lines are equal by value and the gain is invisible to any
value-sum. The moving-average fold recovers it because it removes units at the
*running average* rather than at the sale price — the property
`cli-record-and-balances.md` §6.4 chose the fold for, now load-bearing for a
second reader.

For a euro-only ledger, which is all expense splitting needs, `unit_price` is 1
and the two formulas coincide, so this is invisible until securities are held.
It is written down because the shorter formula will look like an obvious
simplification to whoever reads this next, and there is no failing test at the
moment they try it.

**"At cost" is in the output label**, not implied. A holding bought at 100 and
now worth 140 is reported at 100, and the column header says so.

### 9.4 The extension seam for market valuation

When the price feed lands, `net-worth` swaps `average_cost` for the latest
`Price` for that unit and the shape of the computation — sum of
`quantity × per-unit value`, per section — is unchanged. The seam is
`UnitBalance`, which already carries the quantity and is already the contract
between the fold and its presenters. No abstraction is introduced now to
anticipate it: there is one valuation and the second one is a different spec.

---

## 10. Migrations and downgrades

**Three migrations, one per schema-bearing slice**, as the classification
design established — 018, 019 and 021 land independently and each must
upgrade *and* downgrade on its own. The chain stays linear; no Alembic branch.

| slice | adds | downgrade |
|---|---|---|
| 018 | the `People` account row | refuse if it has children or any lines; else delete |
| 019 | `splits` | refuse if any row exists; else drop |
| 021 | `split_groups`, `splits.group_id` | refuse if any group exists or any `group_id` is set; else drop column, drop table |

### 10.1 018 — seeding a row from a migration

No DDL. One `INSERT` into `accounts` with `name='People'`, `type='asset'`,
`parent_id=NULL`, and an explicit `created_at` — the column is `NOT NULL` with
a *Python-side* default, so a raw insert that omits it fails.

**The upgrade refuses on a name collision rather than letting the constraint
fire.** `uq_account_name` is global, so an install that already has an account
called `People` would abort mid-migration with `UNIQUE constraint failed:
accounts.name`. A `SELECT` first, and a `RuntimeError` naming the existing
account and telling the user to rename it, costs one query and turns a
SQLite message into an instruction. Verified against the live `kohle.db`: it
holds `checking`, `checking_3`, `checking_4` and nothing else, so no collision
exists today.

The downgrade counts children and lines before touching anything, and refuses
if either is non-zero — deleting a People root that has person accounts under
it would orphan them (or be refused by `PRAGMA foreign_keys=ON` with a worse
message), and the accounts hold real balances.

### 10.2 021 — adding a foreign-key column to SQLite, which does not work the obvious way

**`op.add_column` with an inline `sa.ForeignKey` fails on SQLite.** Verified,
Alembic 1.18.3 / SQLAlchemy 2.0.46 / SQLite 3.45.1 in this venv:

```
NotImplementedError: No support for ALTER of constraints in SQLite dialect.
Please refer to the batch mode feature ...
```

Alembic renders the column and then tries to add the constraint as a separate
`ALTER`, which SQLite has no syntax for — even though SQLite itself accepts
`ALTER TABLE splits ADD COLUMN group_id INTEGER REFERENCES split_groups(id)`
directly, and enforces the key afterwards (also verified).

Use `batch_alter_table`, which rebuilds the table and preserves its rows
(verified: the pre-existing row survived with `group_id = NULL`):

```python
with op.batch_alter_table("splits") as batch:
    batch.add_column(sa.Column("group_id", sa.Integer(), nullable=True))
    batch.create_foreign_key("fk_split_group", "split_groups", ["group_id"], ["id"])
```

Batch mode is already precedented here — `7f3c1d9a2b40_multi_unit_ledger.py`
uses it on `accounts`. Chosen over `op.execute` with raw SQL because the raw
form hard-codes a dialect into a migration for no gain.

This is worth recording alongside the classification design's opposite
finding: `op.drop_column` *does* work directly on SQLite (3.35+), so the
downgrade needs no batch block and the asymmetry is real rather than a
mistake.

### 10.3 The refusal standard

Each `downgrade()` opens with a `_refuse_if_unrepresentable()` modelled on the
existing migrations: count what would be destroyed **before any schema
statement**, and `raise RuntimeError` naming the counts and telling the user to
back up `kohle.db` first. Counting first is what makes a refusal leave the
database exactly as it was, which
`tests/test_migration_downgrade.py` asserts.

Dropping a populated `splits` table loses the link between every imported line
and the entry that split it — the entries survive, but which of them is a
split, and of what, does not. Dropping `split_groups` loses every trip label.
Both refuse. In practice these downgrades will almost always refuse, which is
the same honest outcome the multi-unit migration reaches for any ledger with
entries in it.

---

## 11. The decision categories

### State and data lifecycle

**One `split-line` invocation is one transaction, and on the edit path it
covers two journal entries plus a row update.** The reversal of the old
allocation, the new split entry, and the `splits` row's new
`adjusting_entry_id` must land together or not at all: a reversal committed
without its replacement leaves the line unsplit while the `splits` row still
claims a split, and a new entry committed without the row update leaves the
ledger split twice with only one of them findable. `DbTransaction.execute`
commits once at the end, and any `Err` returned from the use-case closure rolls
all of it back. Partial completion is not observable anywhere in this slice.

The same holds for `unsplit-line` (mirror entry + row update) and for
`split-line` on a fresh line (entry + row insert).

**The one construct that would break this is the same one the classification
design named**: nothing inside a use case may be a `UnitOfWork`.
`SplitImportedEntry` posts two entries by calling `post_entry` twice with the
same `ctx`; wrapping either in its own unit of work would commit and close the
session between them.

**Reversibility.** The ledger stays strictly append-only: this slice never
edits, voids or deletes a posted entry or line. Undo and edit are further
entries, which is the `reclassify` precedent applied unchanged. The *annotation*
layer is mutable in exactly one controlled place — `splits.adjusting_entry_id`
and `splits.group_id` — audited through `crud_update`, and losing no
information, since every allocation the row ever pointed at is still a posted
entry.

**Replayability.** Splitting is deliberately **not** idempotent in the
`ImportStatement` sense: re-running `split-line` with the same arguments
reverses the existing split and posts an identical one, leaving balances
unchanged and two more entries in the journal. That is the same trade `record`
and `reclassify` already take — hand-entered corrections are facts, and a
content hash would make the second one collide.

**Auditability.** Every write goes through a `crud_*` decorator, so the
adjusting entries, the reversals, the `splits` rows, and the groups all appear
in `list-operations`, one group per command. The single deliberate exception is
the People root seeded by migration (§3.1).

**Nothing about a settlement suggestion is stored**, per issue 023. `SettleUp`
and `WhoOwesWhat` and `NetWorth` write nothing and, since group creation is
lazy, leave no `OperationGroup` behind.

### Error propagation

Unchanged in structure; the existing three representations and two conversion
seams hold. What this slice adds at each layer:

1. **Infrastructure** — untouched. `DbTransactionContext.run` still converts
   arbitrary failure into `UniqueViolation` / `InfrastructureError`. The
   `BLE001` override in `AGENTS.md` continues to apply there and nowhere else.
2. **Services** — `split_services` maps the `split_groups.name` unique
   violation to `DuplicateSplitGroup` and everything else to `SplitError`.
   `uq_split_journal_entry` gets **no** named mapping: the use cases read the
   row before writing it, so a violation is unreachable from the CLI, and a
   named error for it would be a message no user can produce.
3. **Use cases** — one new family and six aliases in `domain_errors.py`:
   ```
   SplitError(Exception)
     NotAPersonAccount(name)
     SplitDoesNotSumToLine(line_quantity, given)
     NoSplitForEntry(entry_id)
     EntryAlreadySplit(entry_id)
     SplitGroupNotFound(name)
     DuplicateSplitGroup(name)
     EmptySplitGroupName

   SplitEntryError    = AccountError | ClassificationError | JournalError | SplitError
   UnsplitEntryError  = JournalError | SplitError
   AddSplitGroupError = SplitError
   WhoOwesWhatError   = AccountError | JournalError
   SettleUpError      = AccountError | JournalError | SplitError
   NetWorthError      = AccountError | JournalError
   ReclassifyError   += SplitError
   ```
   `AccountNotFoundError`, `PostingToNonLeafAccount` and
   `NoClassificationForEntry` are reused rather than twinned — they are the
   same conditions, reached from a new command.

   **One family, not two, despite two new tables.** `rules` and
   `classifications` got separate families because a caller distinguishes them;
   here every use case that touches a group also touches a split, so a
   `SplitGroupError` family would exist only to be unioned back together at
   every call site.
4. **CLI** — still never inspects an error type; still prints `str(err)`. Every
   new error defines `__str__`, which is what makes issues 019's and 020's
   "clear error, not a traceback" criteria fall out with no CLI work.

Two places where a layer deliberately drops or changes information, both
stated so they read as decisions:

- `split_by_entry_service`'s `NoSplitForEntry` is **swallowed** by
  `SplitImportedEntry` and by `Reclassify`, where "no split" is the normal
  case (§5.2). It is **propagated** by `UnsplitEntry`, where it is the error.
- `NoClassificationForEntry.__str__` is reworded to cover both of its callers
  (§4.2).

### Concurrency and ownership

**Single threaded, no shared mutable state, no concurrency of any kind.**
Stated rather than assumed, because two things in this slice would break
quietly if it stopped being true.

`settle` mutates a working copy of the positions mapping as it drains it. It
takes a `Mapping` and must copy rather than mutate the caller's dict — the
caller's dict is derived from account balances and is reused for the report
rows printed alongside the suggestions. This is a local in a pure function, and
the only reason it is worth a sentence is that "mutate in place to avoid a
copy" is a plausible-looking optimisation on a function whose input is
elsewhere on screen.

`SplitImportedEntry` accumulates `LineSpec`s in a local list and posts twice
against one borrowed `ctx`. It borrows the caller's transaction context and
never takes ownership of a session — the `Session` is owned by
`DbTransaction`, which closes it in a `finally`.

Every value crossing a layer boundary is a frozen dataclass: `PersonShare`,
`PersonBalance`, `GroupAllocation`, `SuggestedTransfer`, `NetWorthReport`,
and the reused `UnitBalance` and `LineSpec`. No ORM instance crosses it —
the session is closed by the time the CLI reads a result, which is why
`WhoOwesWhat` returns `PersonBalance` rather than `Account` rows.

SQLite's single-writer file lock is unchanged; a concurrent TUI would still get
"database is locked". Not addressed, not made worse.

### Reuse

Used rather than reimplemented:

- **`post_entry`** for all three entry shapes this slice posts — the split, its
  reversal, and the undo. It gains nothing and needs no parameter; this is the
  fourth feature to use it as the extension point the first design intended.
- **`Classification`** as the handle onto an imported line (§4.2). The split
  path does not re-derive which line is the counterpart, and does not
  introduce a second way of asking.
- **`Reclassify`'s mirror-the-original-line trick** (§4.3), which removes the
  expense/income branch from the split exactly as it did from the correction.
- **`descendant_account_ids_service`** for People-branch membership and for
  per-person balances — the recursive CTE, with its `UNION`/id-only
  termination property, used unchanged and for the third distinct purpose the
  original design predicted.
- **`account_lines_service`** and the moving-average fold for every balance in
  this slice, including net worth's.
- **`UnitBalance`** as the per-unit balance contract, in three new places.
- **`get_account_by_name_service`**, **`list_child_accounts_service`**,
  **`list_accounts_service`**, **`account_has_children_service`** (through
  `validate_lines`) — all existing, all unchanged.
- **`DuplicateLineInEntry`**, **`PostingToNonLeafAccount`**,
  **`AccountNotFoundError`**, **`NoClassificationForEntry`** — existing errors
  for existing conditions.
- **`crud_create` / `crud_update`** and the whole `UnitOfWork` /
  `DbTransactionContext` machinery. `crud_update` gains its second caller,
  which is the test of whether the classification design was right to add it.
- **`add-account`** as the way to create a person (§2.1) — the single largest
  piece of "code not written" in this slice.
- **`record`** as the way to execute a settlement, including a person-to-person
  one (§2.3).
- **`batch_alter_table`**, `_refuse_if_unrepresentable`, the
  `tests/test_migration_downgrade.py` shape, `tabulate`, `DecimalParamType`,
  the colon-separated option value, the `_cmd` name derivation, and the
  `No <things>` empty-output convention — house style throughout.

Introduced here and worth reusing next:

- **`account_balance(ctx, account_id)`** — the balance of one account as a
  `ctx`-taking function rather than a use case, so anything inside a
  transaction can ask for a balance without opening a second one. Three callers
  on arrival.
- **`aggregate_by_unit`** — promoted from private on gaining its second
  module's caller. The promotion is the whole change; the fold is untouched,
  and its order-dependence comment goes with it.
- **`settle`** — the pure netting function. Any future "simplify these
  balances" question (a TUI panel, a per-group variant) calls it rather than
  re-deriving the greedy.
- **`Split`** — the link from an imported line to the entry that currently
  adjusts it. It is the shape any future line-level correction with an
  undo would take.

### Extension points

- **`post_entry`** continues as the extension point for new ways of making
  entries. This slice is its fourth consumer and changes nothing about it,
  which is the evidence that the contract holds.
- **`UnitBalance`** is the seam where market valuation replaces cost valuation
  in `net-worth` (§9.4). The contract that must stay stable is that it carries
  quantity and unit separately from any per-unit value.
- **`settle`'s signature** — a mapping of participant to signed position,
  returning transfers — is where an exact-minimum solver would slot in if the
  greedy ever proves insufficient (§8.1). Nothing is abstracted for it; the
  signature being pure and total is the whole affordance.
- **`Split.group_id` being nullable** is what makes grouping additive. Any
  future per-group feature (a trip report, a per-group export) reads the same
  foreign key.

**No plugin surface is added.** The `kohle.plugins` entry-point group is for
statement importers and, later, price fetchers. Neither splitting nor
settlement is a plugin seat.

**No abstraction for "a correction to a line".** `Classification` and `Split`
are two records with the same *shape* — one row per entry, a mutable pointer at
the current state, `crud_update` to move it — and a shared base class or a
generic `Correction` is the obvious next thought. It is not built: they carry
different payloads (an account id versus an entry id), they are read by
different queries, and a common ancestor would exist to hold one unique
constraint. The shape is a pattern worth recognising, not a class worth
extracting.

### Build vs. buy

- **Debt simplification — build**, about twenty lines (§8.1). Evaluated:
  `networkx` (min-cost-flow via `network_simplex`) solves a strictly harder
  problem — it minimises *cost* over a weighted graph, not the *number* of
  transfers, and every edge here has equal cost, so it would return an optimal
  flow with no fewer transfers than greedy while adding a dependency with a
  `scipy`/`numpy` footprint. An exact minimum-transaction solver is a subset-sum
  partition search and is discussed and declined in §8.1. There is nothing on
  PyPI that does the specific thing and is smaller than doing it.
- **Group storage — build**, a two-column table through the existing
  `crud_create` / `UnitOfWork` machinery. The alternative considered was a
  string label on the entry, rejected in §2.2 for reasons of referent rather
  than of cost.
- **Person accounts — buy nothing, build nothing.** They are `Account` rows
  under a root, created by the existing command. The alternative — a `Person`
  table with its own CRUD — is the parallel subsystem the whole spec exists to
  avoid, and it would need its own balance machinery the moment anyone asked
  what someone owes.
- **Net worth at cost — build**, and it is four lines over existing pieces
  (§9.2). Evaluated and rejected: deferring to `beancount`'s or `ledger`'s
  reporting, which is not a component that can be dropped in — adopting one
  replaces this project's storage model rather than extending it, as the first
  design already recorded.
- **Adding a FK column on SQLite — buy**, Alembic's `batch_alter_table`, after
  verifying that the direct route does not work (§10.2).
- **CLI plumbing, decimal parsing, table rendering — buy**, unchanged: Click,
  `DecimalParamType`, `tabulate`.

### Abstractions introduced

Each with the problem forcing it. Anything without one is not here.

| Abstraction | Forcing problem |
|---|---|
| `Split` | Undo and edit need "the current split of this line" to be a phrase with one referent, and nothing in the ledger links an adjusting entry to what it adjusts (§4.4). |
| `SplitGroup` | A group needs a stable referent so that two spellings are not two trips and the set of groups can be listed; a string column has neither (§2.2). |
| `PersonShare` | The CLI holds a person *name* and cannot resolve it without a `Session`; the same `LineInput` problem, and a bare `tuple[str, Decimal]` makes transposition type-check. |
| `PersonBalance` / `GroupAllocation` | The session closes before the CLI reads the result, so nothing ORM-shaped may cross the boundary. `GroupAllocation` additionally makes the "every group, even empty" listing expressible (§7.2). |
| `SuggestedTransfer` | Three values that are meaningless apart, crossing the use-case boundary; and `payer`/`payee` being `str \| None` is what encodes "you" without a magic name a person could collide with. |
| `NetWorthReport` | Two sections and three derived totals; returning a bare pair of lists would put the total's arithmetic in the CLI, where a ledger number must not be computed (§9.3). |
| `settle` (as a pure function) | Makes every decision in §8.1 — the greedy, the tie-break, the participant set — testable without a database, the treatment `match_rule` and `aggregate_by_unit` already get. |
| `account_balance(ctx, …)` | Three callers need one account's balance *inside* an existing transaction; the existing entry point is a `UnitOfWork`, and calling it from within a use case would commit and close the session mid-run. |

Explicitly **not** introduced, having no forcing problem:

- A new `AccountType` or `AccountKind` for people (§2.1). The tree is the
  marker.
- A `Person` entity, a `people` table, or an `add-person` command. A person is
  an `Account`.
- A `split_shares` child table, or `own_share` / share columns on `Split`
  (§4.4). The adjusting entry's lines are the shares.
- A `Correction` base class over `Classification` and `Split` (above).
- A `Settlement` record. Issue 023 requires that nothing about a suggestion is
  stored, and executing one is an ordinary `record`.
- A `PersonUnitBalance` twin of `UnitBalance` (§7.1).
- A `--replace` flag on `split-line` (§5.3), a `list-groups` command (§2.2), or
  a `list-splits` command — the last because no acceptance criterion asks for
  it and `entries-in-period` now prints the entry ids that `unsplit-line`
  takes.
- Any validation that a child of `People` is typed `asset` (§2.1).

### Alternatives rejected

Consolidated; each is argued where it arises.

| Rejected | Where | Short reason |
|---|---|---|
| Nesting `People` under an existing financial root | §2.1 | folds receivables into that account's rollup; `balance Checking` would report money not in the bank |
| A new `AccountType`/`AccountKind` for people | §2.1 | a second encoding of subtree membership that can disagree with the tree; a person's sign flips, a type column cannot |
| An `add-person` command | §2.1 | `add-account` with two arguments pre-filled |
| Validating that a person account is typed `asset` | §2.1 | reporting is subtree-based, so the check rejects input that already behaves correctly |
| A free-text group label on `journal_entries` | §2.2 | two spellings become two trips, with no way to list or rename |
| Hanging groups off `OperationGroup` | §2.2 | the audit trail is per use-case run and would fragment a trip; gives the audit layer a domain meaning |
| `group_id` on the adjusting entry | §2.2 | the adjusting entry is replaced on every edit, so the tag would have to be copied forward |
| Auto-creating a group on first `--group` use | §2.2 | a misspelling silently starts a second trip; breaks the strict-lookup rule for user-typed names |
| A `list-groups` command | §2.2 | `who-owes-what --by-group` already enumerates every group, including empty ones |
| Running debt simplification on group totals | §2.3 | settlements belong to no group, so group totals never fall; suggests transfers for debts already paid |
| Making settlement transfers group-taggable | §2.3 | a `record` variant that knows about groups is the new settlement mechanism the spec closes |
| Excluding the user from the netting | §2.3 | the debt graph is a star, so there would be nothing to simplify |
| A single bare net-worth number | §2.4 | the user cannot tell whether receivables were counted — the exact failure issue 024 names |
| Receivables as a subtotal outside the net-worth figure | §2.4 | the spec requires that receivables count toward net worth |
| Get-or-create for the `People` root at first use | §3.1 | `list-accounts` on a fresh install would be missing a branch issue 018 requires |
| Swallowing a missing `People` root into an empty report | §3.3 | it means the database is behind its migrations, not that nothing has been split |
| `--mine` defaulting to the remainder | §4.1 | makes the sum check unfalsifiable, so issue 019's last criterion is satisfied only vacuously |
| Splitting by value rather than by quantity | §4.1 | contradicts the spec's rule that a split reuses the line's recorded quantity, unit and price |
| Asking the user which account to split away from | §4.2 | the `Classification` row already answers it, and a second answer can disagree |
| The two-line shift (`cr expense, dr person`) instead of reverse-and-re-post | §4.3 | issue 019 requires a re-post; the entry stops stating the whole allocation and `--mine` becomes validation-only |
| Storing the shares on the `Split` row or a child table | §4.4 | a second copy of what the adjusting entry's lines already say, with nothing keeping them in agreement |
| Soft-deleting the `splits` row on undo | §4.4 | the unique constraint would then block ever re-splitting that line |
| `Result[Option[Split], …]` for the split lookup | §5.2 | the only service in the codebase reporting absence differently from the rest |
| Folding an edit's reversal and re-post into one entry | §5.3 | two credit lines on one account violate `uq_journal_line_entry_account_unit_side` |
| A `--replace` flag on `split-line` | §5.3 | two commands for one intent, with an order the user has to know; the operation is atomic and reported |
| `--group`'s absence meaning "keep the existing group" | §5.3 | invisible state; the command the user typed should be what the split says |
| Making `Reclassify` split-aware instead of refusing | §5.4 | needs the split's line detail in `classification.py`, closing a use-case cycle, to avoid a two-command detour |
| Recording a split on the `Classification` row | §5.4 | a split is not a classification decision; it would poison the labelled dataset with corrections no human made |
| Labelling group figures and person balances with the same column name | §7.2 | they answer different questions and will be read side by side |
| An exact minimum-transaction solver | §8.1 | NP-hard subset-sum partition, differing from greedy only in cases nobody constructs by accident |
| `networkx` min-cost-flow | build vs. buy | minimises cost, not transfer count; equal-cost edges make it no better than greedy, for a `scipy` dependency |
| A default cash account for settlements | §8.3 | a configuration mechanism this codebase does not have |
| Net worth as `sum(line.value)` | §9.3 | silently drops realised gains: buy 10@100 then sell 5@130 totals 0 instead of 150 |
| Including income and expense accounts in net worth | §9.2 | every entry balances, so the total would be identically zero |
| Market valuation in this slice | §9.1 | needs the price feed `portfolio-and-profit-reporting.md` owns |
| `op.add_column` with an inline `sa.ForeignKey` | §10.2 | `NotImplementedError` on SQLite (verified); batch mode is required |
| One combined migration for all three slices | §10 | the slices land independently and each must downgrade independently |

---

## 12. Issue mapping

| Issue | Lands |
|---|---|
| 018 People branch | `PEOPLE_ROOT` (§3.1); the seeding migration and its collision guard (§10.1); the `people_root` test fixture (§3.2). No new command — `add-account --parent People` (§2.1) |
| 019 split an imported line | `Split` + migration (§4.4, §10); `split_services.py`; `PersonShare` and `SplitImportedEntry` (§4.1–4.3); `NotAPersonAccount`, `SplitDoesNotSumToLine`; the `EntryAlreadySplit` guard in `Reclassify` (§5.4); `entry_id` on `entries-in-period` (§4.1) |
| 020 undo or edit a split | `UnsplitEntry` (§5.1); the replace path in `SplitImportedEntry` (§5.3); `NoSplitForEntry`; `set_split_adjusting_entry_service` through `crud_update` |
| 021 group splits under a trip | `SplitGroup` + `splits.group_id` + migration (§6, §10.2); `AddSplitGroup`; `splits_in_group_service`; `--group` on `split-line` |
| 022 report who-owes-what | `account_balance` and the `aggregate_by_unit` promotion (§9.2, §7.1); `PersonBalance`, `GroupAllocation`, `WhoOwesWhat`; `who-owes-what [--by-group]` |
| 023 suggest settling transfers | `settle` and `SuggestedTransfer` (§8.1); `SettleUp`; `settle-up [--group]` |
| 024 receivables in net worth | `NetWorth` + `NetWorthReport` in `journal.py` (§9); `net-worth`. No schema change |

Dependency order is the issue order. 018 precedes everything because nothing
can post to a person account before the branch exists. 019 precedes 020 and
021. 022 depends on 021 only for the `--by-group` half; its global half needs
only 018, and it can land in that order if the slices are re-cut. 023 depends
on 022 for the balances it nets. 024 depends only on 018.

---

## 13. Testing notes

Extends the existing four-layer pattern — pure functions with no fixture,
services and use cases against the `session` / `session_factory` fixtures, CLI
through `CliRunner` with an injected factory.

**Pure, no database.** `settle` takes the bulk of the unit tests, because every
decision in §8.1 lives in it and none of them needs a session: the spec's own
acceptance case (Alice +50, Bob −50, you 0 → **one** transfer, not two or
three); the star case (two people both owing you → two transfers, nothing to
simplify); a chain (Alice +50, Bob −30, Carol −20 → two transfers, not three);
equal-amount ties resolving identically across runs; an all-zero input
returning no transfers; and the invariant that the emitted transfers applied to
the input drive every position to exactly zero.

**The `people_root` fixture, and why it is not optional.** Tests build the
schema from `base.metadata`, not from Alembic, so the migration's seeded row
does not exist (§3.2). Every splitting test needs the fixture, and the failure
without it is an `AccountNotFoundError` from a use case that looks correct.

**The scenario tests**, in the shape of `test_cash_envelope_scenario.py`:

- The spec's own test: import an €80 dinner, split 32/48 to Alice, assert
  `Eating out` holds 32 and `People:Alice` holds a 48 receivable, and that the
  `splits` row links both entries back to the import.
- Undo: balances return exactly to the pre-split state, the original entry is
  untouched, and the `splits` row survives with `adjusting_entry_id IS NULL`.
- Edit 32/48 → 40/40: both accounts reflect the new shares and all four
  entries (import, split, reversal, re-split) are readable.
- An **income** split: a positive imported amount split with a person, leaving
  the person account **negative**. This is the branch-free mirror of §4.3 and
  it is the case that would be wrong if anyone introduced an expense/income
  branch later.

**Regression guards for the traps this design names.** Each exists because the
code is correct in a way that is easy to break silently:

- Reclassify first, then split: the shares come out of the corrected account,
  not the bucket (§4.2). Split first, then reclassify: refused with
  `EntryAlreadySplit`, and the balances are unchanged by the refusal (§5.4).
- One `split-line` run produces **one** `OperationGroup` holding both entries
  and the `splits` row — the direct extension of
  `test_write_creates_exactly_one_group_holding_its_operations`, and the guard
  against someone turning the reversal into its own unit of work (§11).
- A split whose group is edited away, and a split that is undone, both
  contribute nothing to their group's per-person figures (§6).
- Net worth with a holding that was partly sold: buy 10 @ 100, sell 5 @ 130,
  assert the total is 150 and not 0. This is the §9.3 trap and it is the one
  test that would fail the moment somebody "simplifies" the total to
  `sum(line.value)`.
- A person with a zero balance renders `0.00` and a person never split against
  renders `—` (§7.1) — issue 022's criterion as a test rather than a prose
  claim.
- Net worth with a negative person balance is *lower* than without it — issue
  024's third criterion.

**Use-case level.** `split-line` against a hand-entered `record` entry →
`NoClassificationForEntry`; against an account outside `People` →
`NotAPersonAccount`; with shares summing to 79 on an €80 line →
`SplitDoesNotSumToLine`; with an unknown group → `SplitGroupNotFound`.
`unsplit-line` on a never-split entry and on an already-undone one → both
`NoSplitForEntry`. `add-group` twice with the same name →
`DuplicateSplitGroup`.

**Migrations.** Three additions to `tests/test_migration_downgrade.py` in the
established shape: a clean round trip on empty data and a refusal on populated
data that asserts the schema is untouched. 018 additionally gets the
name-collision refusal on upgrade (§10.1), and 021 gets a test that the
`batch_alter_table` rebuild preserves existing `splits` rows (§10.2).

**CLI.** `split-line` with a malformed `--share` exits non-zero naming the
offending string; `who-owes-what` on a ledger with no person accounts prints
the empty message rather than failing; `settle-up` with nothing outstanding
prints `No transfers needed`; `net-worth` renders the receivables line even
when it is zero.

---

## 14. What the spec and the issues got wrong

Recorded because the design deviates from them, and a later reader needs to
know it was deliberate.

1. **Issue 023's "globally, or scoped to one group" cannot mean group
   *balances*.** Its own last criterion — execute a suggested transfer, re-run,
   see the balances zeroed — is unsatisfiable against group totals, because a
   settlement transfer belongs to no group and never reduces one. `--group`
   scopes *who* is considered, not *what* is netted. §2.3.
2. **"Net worth reporting includes person-account receivables" assumes a net
   worth report that does not exist.** `cli-record-and-balances.md` put net
   worth in its Non-Goals pending a price feed, and
   `portfolio-and-profit-reporting.md` still owns it. This slice builds net
   worth **at recorded cost**, which needs no price source, and draws the
   boundary at market valuation. §9.1.
3. **The spec's "no new handling needed for currency mismatch" is true, but
   only if shares are quantities.** Splitting by *value* would need the line's
   price to divide by, which is the handling the spec says is unnecessary.
   Reading the shares as quantities in the line's own unit makes the claim
   true. §4.1.
4. **Nothing in the issues anticipated the reclassify/split interaction**, and
   without the guard in §5.4 the two features silently corrupt a balance when
   used in one of the two possible orders. This is a change to issue 017's
   shipped behaviour, made by issue 019's slice because that is the slice that
   creates the hazard.
5. **There is no command that prints the entry id `split-line` needs.**
   `list-unclassified` prints one but by definition excludes successfully
   classified lines, which are most of what a user wants to split.
   `entries-in-period` gains an `entry_id` column. §4.1.
6. **"one Alembic migration ... (if it needs seeding) and any groups table"
   does not survive the slice decomposition.** Three, one per schema-bearing
   issue, so each lands and downgrades on its own — the same correction the
   classification design made. §10.
7. **Issue 019's "traceable via `Operation` rows back to the original import"
   overstates what `Operation` carries.** It records what was written, not what
   it refers to; the link back to the import is `splits.journal_entry_id`. The
   criterion holds, through the pair. §4.6.
