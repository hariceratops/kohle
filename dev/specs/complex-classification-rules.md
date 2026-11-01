# Richer classification rules

## Overview

Today a classification rule is a single regular expression and a target
account. It matches when the pattern hits the description, the counterparty
name or the counterparty IBAN (`match_rule` in `kohle/use_cases/rules.py`). A
rule cannot test the amount or the direction, and it cannot require two things
at once. The case this work exists for is money sent to a partner every month.
The same IBAN and the same reference text cover two kinds of payment: a monthly
500 that is a shared household expense, and a one-off 2000 that is an
investment into the partner's account. No rule can tell them apart today, so
the user fixes each odd line with `reclassify`.

This slice changes three things:
- A rule becomes a predicate over a line, built from field conditions combined
  with AND, OR and NOT.
- Rules are edited as a TOML file in `$EDITOR`.
- An explicit command re-runs the rules over lines that are still unclassified.

The rule engine also collects the labelled data a later ML phase will train
on. So every classification, and every change to one, stays fully recorded.

## Goals

- **Conditions.** A rule can test any of these, and matches only when all of
  them hold:
  - a description pattern
  - a counterparty-name pattern
  - an exact IBAN
  - an amount range
  - a direction (`in` or `out`)
  - today's any-field pattern (`any_field`)

  Conditions combine with `any` (OR) and `not` (NOT), and these nest. As
  today, the first matching rule in priority order wins.
- **Amount and direction.** The range is on the absolute amount, includes
  both ends, and either end may be left open. Direction is a separate
  condition. A range whose low end is above its high end is rejected.
  Amounts are compared as exact decimals, never as floats.
- **Pattern and IBAN matching.** Patterns are case-insensitive, as today. An
  IBAN condition ignores spaces and letter case.
- **A line with no counterparty.** If the line has no counterparty name or
  IBAN, a condition on that field does not hold, so `not` over that condition
  holds.
- **Editing rules.** `edit-rules` renders the whole rule set as TOML and
  opens it in `$VISUAL` or `$EDITOR`. If neither is set, the command fails
  with a clear message. On save, the file is parsed and checked. If anything
  is wrong, the editor reopens with the error shown and nothing is applied. If
  the file is valid, the command shows a summary of the change (added,
  retired, unchanged, reordered) and asks before applying it.
- **Non-interactive route** for agents and scripts:
  - `show-rules` prints the current rule set as TOML.
  - `apply-rules <file>` uses the same checks and comparison as
    `edit-rules`. It prints the summary and asks before applying; `--yes`
    skips the question. It exits non-zero on any error.
- **Rule identity is decided by content.** Rule ids never appear in the file.
  - A rule whose conditions and target account are unchanged keeps its id. If
    it was moved in the file, only its priority changes.
  - A change to the note alone updates the note.
  - Any other change retires the old rule and adds a new one, so every
    `Classification.matched_rule_id` keeps pointing at the rule that actually
    matched.
- **Rendering round-trips.** The same rule set always renders as the same
  text, and that text parses back to the same rule set. Applying an unchanged
  file writes nothing and leaves no audit-trail entry.
- **Existing rules carry over.** Each existing rule becomes one `any_field`
  condition and keeps its id. A statement imported after the migration
  classifies exactly as it would have before.
- **Existing commands keep working.**
  - `add-rule` keeps its single-pattern form and adds the new rule at the end
    of the order.
  - `remove-rule` is unchanged.
  - `list-rules` shows one row per rule in evaluation order: id, account, and
    the conditions in the compact form used in the file.
- **Re-running the rules over past lines.** `classify-rules` runs the current
  rule set over lines still sitting in `Unclassified Expense` or `Unclassified
  Income`. It then:
  - previews each line that would move: date, description, amount, the bucket
    it is in now, the target account and the rule that matched;
  - asks before applying (`--yes` skips the question);
  - posts each move as a correcting entry, the same way `reclassify` does.

  It never touches a line a rule already classified or a human reclassified.
  Changing rules never reclassifies anything by itself; only this command
  does.
- **All-or-nothing.** `edit-rules`, `apply-rules` and `classify-rules` each
  either apply fully or leave the ledger untouched. That holds for a failed
  check, a declined prompt, an aborted editor and a crash part-way through.
  Each one that writes is recorded in the audit trail as one group.
- **Write commands.** `edit-rules`, `apply-rules` and `classify-rules` are
  write commands, so a reader device refuses them. `show-rules` is read-only.
- **Testable.**
  - Two rules on the same IBAN, one with `amount = { min = 400, max = 600 }`
    and one with `{ min = 1500 }`, send a 500 and a 2000 outgoing payment from
    one statement to two different accounts.
  - Running `show-rules` and feeding its output to `apply-rules --yes` reports
    no changes and writes nothing.

## Non-Goals

- An ML classifier, or a plugin contract for classifiers.
- Suggesting new rules from corrections.
- Day-of-month or other date conditions.
- Detecting rules that can never match because an earlier rule always wins.
- A rule with no conditions at all. It is rejected, because the unclassified
  buckets already catch everything no rule matches.
- Flags on `add-rule` for IBAN, amount or direction. In this version those
  conditions are reached only through the file.
- Re-running rules over lines that a rule or a human already classified.
- Editing rules from the TUI.
- Compiling rules to SQL, or any optimisation of rule evaluation.
- Machine-readable output beyond the TOML rendering.
- Renaming existing commands, or moving them into command groups. That
  belongs to `cli-command-naming`.

## Technical Approach

- **Platform.** Python 3.12, layered as `AGENTS.md` describes. The file is
  read with `tomllib`, which supports TOML 1.0. How the file is written (a
  canonical renderer of our own, or a new dependency) is the architect's
  decision.
- **File layout.** Each rule is a `[[rule]]` entry, and the order of the
  entries is the priority. Each rule has an `account`, an optional `note`,
  and a `when` table. Keys in `when` are ANDed together; `any = [...]` is OR,
  and each of its items is an AND of its own keys; `not = {...}` is NOT. TOML
  1.0 does not allow an inline `{...}` table to span lines, so each OR
  alternative sits on its own line. That is readable at shallow nesting; deep
  nesting means long lines. This has been checked against `tomllib`:

  ```toml
  [[rule]]
  account = "Household"
  note = "monthly share to partner"
  [rule.when]
  iban = "DE89..."
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

- **Storage.** A rule is now a condition tree. The brief's idea of one
  database column per condition cannot hold OR and NOT. How the tree is
  stored (for example flattened into rows) is the architect's choice. Rules
  stay immutable at the storage level.
- **Matching.** `match_rule` stays pure and session-free. It evaluates the
  tree on each line, children before parents, and stops evaluating an AND or
  an OR as soon as its result is known. It is now also given the line's
  signed amount.
- **Checks that reject a file.** Each error names the rule by its position in
  the file and names the key at fault. A file is rejected for:
  - a TOML syntax error
  - an unknown key
  - a pattern that does not compile
  - an account that is missing or is not a leaf
  - a range whose low end is above its high end
  - an empty `any`, or an empty `not`
  - a rule with no conditions
  - two rules with identical content, because identity by content cannot
    tell them apart
- **A deleted rule set.** An empty file, or one with every rule deleted,
  retires all rules. The confirmation summary shows that count before
  anything is applied.
- **Concurrent changes.** If the stored rules changed after the file was
  rendered (for example an `add-rule` from another shell), `edit-rules` and
  `apply-rules` refuse to apply rather than silently overwrite that change.
- **Places this touches.**
  - The `Rule` model and a new Alembic migration that converts each existing
    pattern into an `any_field` condition.
  - `compile_rules` and `match_rule`, and their call in
    `ImportStatement.execute` (`kohle/use_cases/journal.py`).
  - `post_entry` and the correction path of `reclassify`, for
    `classify-rules`.
  - `list-rules` in `kohle/app/cli/cli.py`.
  - The reader-device write guard.

## Open Questions

- **What does the user's "explicit classify-rule" mean?** It is read here as
  a separate command, `classify-rules`, that re-runs the rules over past
  lines and is kept apart from `edit-rules` and `apply-rules` so that changing
  rules never reclassifies anything. The user should confirm both that
  reading and the name.
- **Which past lines does `classify-rules` cover?** The default is lines
  still in the unclassified buckets, with lines a rule or a human already
  classified left alone. The user did not state this, so it can be
  overruled.
- **How is a re-run recorded in `Classification`?** Today `corrected = True`
  means a human changed the line. A move made by `classify-rules` must stay
  distinguishable from a human correction, and must record which rule
  matched; otherwise the ML training labels are wrong. The architect decides
  the shape.
- **Do `apply-rules` and `classify-rules` ask before applying?** The default
  is to ask, with `--yes` to skip the question. The user did not state this,
  so it can be overruled.
- **Should `add-rule` get condition flags?** The default is no for this
  version (see Non-Goals). The user did not state this, so it can be
  overruled.
