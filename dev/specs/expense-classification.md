# Automatic expense classification

## Overview

Imported statement lines currently land in one of two catch-all buckets,
`Unclassified Expense` or `Unclassified Income` — `ImportStatement`'s own
docstring already says "choosing a better counterpart account is the
classifier's job," so this seam was anticipated, not retrofitted. This slice
builds that classifier: a rule engine matching each imported line's
description and counterparty against a user-maintained set of rules, applied
automatically at import time, with every proposal and every correction
recorded. The rule engine is not a placeholder for a future ML model bolted
on later — it is the mechanism that produces the labelled data an ML phase
would need, which only holds if what it proposed, what a rule matched, what
account the line ended up on, and whether a human changed it are all
captured from the first classified line, not added retroactively.

## Goals

- `ImportStatement` calls the rule matcher for every imported row instead of
  unconditionally routing to the unclassified buckets. A row that matches a
  rule posts directly to that rule's target account; a row that matches no
  rule still falls back to `Unclassified Expense`/`Unclassified Income`
  exactly as today.
- Rules live in a new `Rule` table — pattern, target account, priority —
  managed by new CLI commands (`add-rule`, `list-rules`, `remove-rule`),
  matching how `Account` and `Unit` are already DB rows with CLI CRUD rather
  than file-based config. Nothing here depends on the TUI, but a DB table is
  what makes rules reachable from it later through the existing
  `model_serde` machinery, for free.
- **Every classification is recorded, from the first line classified.** Per
  imported line: the proposed account, which rule matched (nullable — a
  fall-through to the unclassified bucket matched no rule), the final
  account, and whether a human corrected it. This is not a nice-to-have
  bolted on afterward — the brief's own analysis calls it "the one decision
  in this brief that is expensive to retrofit and nearly free to build in
  now," and this PRD treats it as a first-class requirement of the initial
  slice, not a follow-up.
- A `list-unclassified` (or equivalent) CLI command surfaces what fell
  through to the unclassified buckets, so there is a way to find what still
  needs a rule or a manual fix without scanning `entries-in-period` by hand.
- A `reclassify` command corrects a wrongly-classified line — whether it was
  matched-and-wrong or fell through to the unclassified bucket — by posting
  an adjusting entry, never by rewriting the original line. This is forced
  by the codebase, not a preference: `cli-record-and-balances` already
  establishes append-only correction by reversing entry for this exact
  `JournalEntry`/`JournalLine` model, and there is no mechanical alternative
  today — `crud_create` hardcodes `action="create"`, there is no
  `crud_update`, and nothing writes `Operation.field`/`Operation.state`. A
  `reclassify` that rewrote history would be inventing an update path this
  codebase deliberately doesn't have.
- **Counterparty identity is captured on `JournalEntry`, closing a gap the
  brief assumed was already there.** The brief says rules match on
  "description and counterparty," but tracing the current import path shows
  counterparty doesn't survive today: `ImportStatement`'s schema requires an
  `iban` column, validates it, and then discards it without storing it
  anywhere (`kohle/use_cases/journal.py`, `ImportStatement.execute`); the
  Deutsche Bank importer renames `Beneficiary / Originator` to `beneficiary`
  and then drops the column entirely before `ImportStatement` ever sees it
  (`kohle_deutsche_bank_importer.py`, rename at the `.rename(columns=...)`
  call, drop in the following `.drop(columns=[...])`). Closing this gap is
  in scope for this slice: nullable `counterparty_name` and
  `counterparty_iban` columns on `JournalEntry`, an Alembic migration adding
  them, the importer plugin contract extended so a `StatementImporterPlugin`
  is expected to supply both, and the Deutsche Bank importer fixed to keep
  `beneficiary` instead of dropping it and to pass `iban` through instead of
  only validating it.

## Non-Goals

- **The ML classification phase.** Model choice, local vs. hosted, and
  ongoing accuracy tuning are a genuinely separate track per the vision
  document ("the ML phase is a genuinely separate track, not a
  continuation") and per the brief's own rejected direction ("building the
  rule engine and the model together... the rule engine has to run first
  regardless, because it is what generates the labels"). Deferred to a
  future spec, once this slice has produced labelled data to train on.
- **A per-row interactive confirmation loop during import.** Every existing
  CLI command in this codebase is a single non-interactive invocation;
  building a propose-and-wait prompt loop for `import-statement` would be a
  new UX pattern introduced solely for this feature. Auto-apply at import
  time, with `list-unclassified` and `reclassify` as the review/correction
  path, is the chosen shape (see Goals).
- **Rule editing from the TUI.** The TUI is unwired (`tui-wiring.md`); rules
  living in a DB table is what makes that reachable later, not something
  this slice wires up.
- **Fuzzy or scored matching, confidence thresholds, or partial matches.**
  The brief specifies a rule engine matching description and counterparty; a
  ranked/fuzzy matcher is ML-adjacent territory and belongs with the later
  phase, not this one.
- **Splitting a classified expense across multiple accounts.** Covered by
  `expense-splitting.md`; out of scope here.
- **Auto-generating rules from corrections.** Corrections are captured (see
  Goals) so a future phase can consume them; this slice does not turn a
  correction back into a new rule automatically.
- **Non-EUR cash / FX handling, and anything the base `record`/`balance`
  slice already deferred** — untouched here, this slice only changes how
  imported lines pick a counterpart account.

## Technical Approach

- Python 3.12, layered `app -> use_cases -> services ->
  infrastructure/domain` per `AGENTS.md`. Reuses `post_entry`
  (`kohle/use_cases/journal.py`) for every entry this slice posts — both the
  classified import line and the `reclassify` adjusting entry — exactly as
  the `cli-record-and-balances` design anticipated ("any future
  entry-creating use case — the classifier in `expense-classification.md`
  ... should call it").
- **Schema additions** (one Alembic migration):
  - `JournalEntry.counterparty_name: str | None`,
    `JournalEntry.counterparty_iban: str | None` — populated at posting
    time from whatever the importer supplied; `None` for hand-entered
    `record`/`record-split` entries, which have no counterparty concept.
  - `Rule` table: pattern (matched against description and/or counterparty),
    target `account_id`, priority (integer, lower matches first), and the
    usual `Archivable` timestamps. Exact pattern syntax (substring, regex,
    or a small DSL) is left to the architect; the brief only specifies
    matching on description and counterparty, not the matching language.
  - `Classification` table (or equivalent — name left to the architect):
    one row per classified journal entry, holding `journal_entry_id`,
    `proposed_account_id`, `matched_rule_id` (nullable FK to `Rule`),
    `final_account_id`, and `corrected: bool`. This is the training-set
    record the brief calls out as expensive to retrofit; `matched_rule_id`
    is this PRD's addition to the brief's own list — "whether a human
    changed it" without "which rule was responsible" doesn't support tuning
    or removing a bad rule, which is the reason the field exists to capture
    corrections in the first place.
- **`ImportStatement` change**: for each row, before choosing the
  unclassified-bucket fallback, run the rule matcher against the row's
  description and counterparty (name and/or IBAN, once populated). On a
  match, post to the rule's target account and write a `Classification` row
  with `proposed_account_id == final_account_id`, `matched_rule_id` set,
  `corrected = False`. On no match, post to the unclassified bucket as
  today, and still write a `Classification` row — `matched_rule_id = None`,
  `proposed_account_id` equal to the unclassified bucket — so
  `list-unclassified` and future rule-tuning work have one place to read
  from regardless of whether a rule fired.
- **Importer plugin contract**: `StatementImporterPlugin.import_statement`'s
  returned dataframe gains an expectation that `beneficiary`-equivalent and
  `iban` columns are present and passed through, not just validated and
  dropped. This is a contract change (`kohle/plugin/importer_plugin.py` and
  `ImportStatement`'s schema check in `kohle/use_cases/journal.py`), and the
  one existing implementation, `kohle_deutsche_bank_importer.py`, needs
  fixing at both points named above to stop discarding the fields.
- **`reclassify` command/use case**: takes an already-classified
  `JournalEntry` (by reference or id — lookup mechanism left to the
  architect, `entries-in-period` already covers browsing) and a new target
  account; posts a reversing pair (credit the wrong account, debit the
  right one) via `post_entry`, and updates the `Classification` row's
  `final_account_id` and sets `corrected = True`. The original entry is
  never edited or deleted.
- **`list-unclassified` command/use case**: queries `Classification` rows
  where `matched_rule_id IS NULL` (or equivalently, where `final_account_id`
  is still one of the unclassified buckets), joined to the underlying
  `JournalEntry` for display — description, counterparty, date, amount.
- **Operation audit trail**: unaffected by this slice's own logic, but
  worth noting given the brief calls out interaction with "the existing
  operation-tracking machinery" — issue 011 (fixed this session, commit
  `eea81a1`) made `OperationGroup` creation lazy, on the first recorded
  write, rather than unconditional. So a `list-unclassified` call, being
  read-only, now leaves no empty group behind; only actual writes
  (classified imports, `add-rule`, `reclassify`) produce `Operation` rows
  and groups. `AGENTS.md` records this as an invariant; this slice's new
  writes (`Rule`, `Classification`, the adjusting entries) go through
  `crud_create` like everything else, so they participate in that trail
  without special-casing.
- **Integration points**: `ImportStatement`
  (`kohle/use_cases/journal.py`), `post_entry`, the importer plugin contract
  (`kohle/plugin/importer_plugin.py`), the one existing plugin
  (`kohle/app/plugins/kohle_deutsche_bank_importer.py`), `Account`/`Unit`
  CRUD patterns as the template for `add-rule`/`list-rules`, and a new
  Alembic migration alongside the existing ledger schema.

## Open Questions

- **Rule pattern language.** Left to the architect — plain substring match,
  regex, or a small DSL over description/counterparty are all consistent
  with the brief, which specifies what rules match on, not how a pattern is
  expressed.
- **`Classification` table name and exact shape** — left to the architect;
  the four fields it must carry (proposed account, matched rule, final
  account, corrected flag) are fixed by the Goals above, the table/column
  naming is not.
- **Priority/tie-breaking when multiple rules match one row** — the brief
  doesn't specify, and this PRD leaves "lower priority number wins, first
  by insertion order on a tie" as a reasonable default for the architect to
  confirm or replace during design, not a user-confirmed contract.
- **`reclassify`'s lookup mechanism** (by journal entry reference, by a new
  id-based lookup, or by browsing `entries-in-period` first) is left to the
  architect, same as `cli-record-and-balances` left `record`'s flag shape
  open.
- **Whether corrections should ever feed back into suggesting new rules**
  is explicitly deferred (see Non-Goals) — flagged here rather than silently
  dropped, since it's the natural next question once `Classification` data
  exists.

Everything else raised during the interview was resolved; no other open
questions remain. In particular, the brief's own five open questions are
now settled: trigger is auto-apply at import time (not propose-and-wait);
rules live in a DB table (not a config file); reclassification is always an
adjusting entry (not a rewrite); captured data is proposed/matched-rule/
final/corrected; and the ML local-vs-API question is out of scope for this
slice entirely, deferred to the future ML-phase spec.
