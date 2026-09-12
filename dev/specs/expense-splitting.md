# Expense splitting

## Overview

Shared expenses distort a personal ledger: a bill partly belonging to someone
else is not fully your expense, and without somewhere to put the other
person's share the totals are wrong or the transaction has to be dropped.
This slice treats a person as an account — living in its own branch of the
account tree, separate from the user's own financial accounts — so a split
is just a multi-line entry against a person account, no parallel subsystem.
Manual n-line entries already exist (`record-split` / `RecordSplitEntry`),
so the gap this slice actually closes is narrower than "record a split":
it is retroactively splitting a line that already arrived through import,
plus the reporting and settlement machinery (who-owes-what, debt
simplification, groups/trips) that make the resulting people-account
balances useful day to day.

## Goals

- People accounts live in a separate branch of the account tree from the
  user's own financial accounts (e.g. a dedicated `People` root), not
  interleaved with cash/asset/expense accounts.
- A CLI command splits an already-imported statement line after the fact:
  the original line's value is divided between the user's own expense
  account and one or more person accounts, posted as an adjusting entry —
  never by rewriting the original line, matching the append-only correction
  pattern `reclassify` already established (no `crud_update`, no
  `Operation.field`/`state` write path exists to rewrite history with).
  Test: splitting an imported €80 dinner line into €32 own-share / €48
  person-share leaves the expense account holding €32 and the person
  account holding a €48 receivable, both traceable via `Operation` rows back
  to the original import.
- Undoing or editing a split is a further adjusting entry against the same
  lines, not an in-place rewrite — the same mechanism `reclassify` uses,
  applied to a split's lines instead of a classification.
- A group/trip concept bundles multiple split expenses under a shared label
  (e.g. "Italy trip"), so balances and settlement can be viewed per group as
  well as per person.
- A reporting command lists who-owes-what: net balance per person account,
  and per group where a split belongs to one.
- Settlement suggestion: given a set of person balances (globally or within
  a group), compute the minimum set of settling transfers that zeroes them
  out (debt simplification / min-cash-flow netting), rather than naively
  pairing up every non-zero balance. Test: three people with net balances
  that cancel through one intermediary produce one suggested transfer, not
  two or three.
- Settling up is a transfer from a person account to a cash account
  (already representable with the existing entry model); no new mechanism
  needed for the transfer itself.
- Net worth reporting includes person-account receivables. Whether they're
  folded into one net worth figure or broken out as a separate subtotal
  (assets vs. receivables) is left to the architect — see Open Questions.
- Currency mismatch (a split denominated in a unit you don't hold) needs no
  new handling: the split's lines use the original transaction's recorded
  quantity, unit, and price exactly as the multi-unit pricing model already
  does for every other line.

## Non-Goals

- **A dedicated "record a new split expense from scratch" entry path.**
  `record-split` already posts an arbitrary n-line entry against arbitrary
  accounts, which is exactly what a from-scratch split needs — building a
  second, split-specific manual-entry command would duplicate it. This
  slice's manual-entry surface is the retroactive split of an *imported*
  line only.
- Itemized/percentage split UI beyond specifying line values directly (no
  bill-scanning, no per-item tax/tip apportionment logic).
- Any change to currency/pricing handling — explicitly closed by the
  currency-mismatch goal above.

## Technical Approach

- Python 3.12, layered `app -> use_cases -> services ->
  infrastructure/domain` per `AGENTS.md`. Reuses `post_entry`
  (`kohle/use_cases/journal.py`) for adjusting entries, same as
  `reclassify`.
- **Account tree**: a `People` (or similarly named) root account, siblings
  of the existing top-level financial accounts, not children of them.
  Exact placement and whether it needs a new `AccountKind`/type marker is an
  architect decision.
- **Retroactive split**: new use case (e.g. `SplitImportedEntry`) that reads
  an existing `JournalEntry`/`JournalLine`, and posts an adjusting entry
  reversing the original counterpart line and re-posting it split across the
  user's expense account and one or more person accounts. Follows the
  `reclassify` precedent for both the reversing mechanism and the
  `Operation` audit trail.
- **Undo/edit**: same adjusting-entry mechanism, applied again.
- **Groups/trips**: likely a new lightweight table linking split entries (or
  their `Operation`/`OperationGroup`) to a named group. Exact schema left to
  design — this PRD only requires that a group can be queried for its
  member splits and their people-account balances.
- **Debt simplification**: a graph/netting algorithm over current person
  balances (within a group or globally), computed at report/suggestion
  time — derived from existing account balances, not stored. Algorithm
  choice (e.g. greedy max-debtor/max-creditor pairing until balances zero)
  left to design.
- **Reporting**: extends the existing balance-reporting layer with a
  who-owes-what view over person accounts/groups, and folds person-account
  balances into net worth calculation.
- Migration: one Alembic migration for the `People` root account (if it
  needs seeding) and any groups table.

## Open Questions

- Net worth presentation: single net-worth figure including receivables, or
  a separate "receivables" subtotal alongside it? Left to the architect;
  the requirement is only that receivables count.
- Group/trip data model: standalone table vs. an attribute on existing
  entries/operations — left to design.
- Debt-simplification scope: does it run within a single group only, or
  also globally across all person accounts regardless of group? Left to
  design, since the user asked for both a group concept and simplification
  without specifying which one bounds the other.
- Exact placement of the `People` root in the account tree, and whether it
  needs its own account-type marker — left to the architect.
