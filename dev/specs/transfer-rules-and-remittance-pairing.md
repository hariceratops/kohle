# Transfer rules and remittance pairing

## Overview

A statement row becomes one entry on the account it was imported into, and a
rule decides only the other side's expense or income category. Two cases do
not fit that shape.

**A transfer between two imported own accounts.** Checking sends 500 to
Savings, and both accounts' statements are imported. Dedup is by native
reference, scoped to the account (issue 026), so the two rows are two
entries:

- Checking −500 against `Unclassified Expense`;
- Savings +500 against `Unclassified Income`.

Net worth is right, but the same 500 shows once as spending and once as
income. That distorts the buckets, `list-unclassified` and anything read off
expense or income accounts.

Today's workaround is a rule on each side routing to a shared asset account,
`Transfers`, which nets to zero once both rows are in. A rule may already
name an own account directly: rule targets are checked only for being a leaf.
Doing so double counts once the counterpart's statement is imported, because
Savings is then debited by Checking's entry and again by its own row.
`reclassify` onto an own account has the same hazard.

**A remittance paid from a euro account, and its reverse.** A remittance
paid by card or by transfer is imported as a euro spend on Checking. There
is no INR row to pair it with, because the Indian bank importer is a
Non-Goal of `multi-currency-and-fx`. Nor is there any way to turn an imported
line into the two-amount form that spec defines (`record ... --to-unit INR
--total X`), which creates an INR lot at the euros actually sent. Rupees
changed back arrive as a euro inflow on Checking, with the same gap: nothing
turns it into the reverse two-amount entry (issue 115) that consumes INR
lots and realises FX gain.

This spec extends classification rules so that one rule kind covers all of
these cases.

## Decisions (made by the user)

- **Rules, not a pairing workflow.** Both cases are handled by
  classification rules. There is no separate suggest-and-confirm pairing
  command, and no automatic merge at import that runs without a rule.
- **A transfer rule targets an own account.** Its action names an own account
  (the counterpart) instead of an expense or income category. A matching line
  becomes a move between the two own accounts.
- **A remittance rule is a transfer-style rule.** Its counterpart is the own
  account that holds a non-base currency (INR). As in
  `multi-currency-and-fx`, the mechanism applies to any non-base currency
  unit, and no code names INR.
- **Corrections and undo use adjusting entries**, as classification does
  today (issue 017, `reclassify`, `classify-rules`). The ledger stays
  append-only: nothing is edited, voided or deleted, and the audit trail
  keeps every step.
- **A correction joins a named fall-through line to a named transfer**, and
  its reverse undoes the join, as `reclassify` corrects one line. Working
  names: `join-transfer LINE_ENTRY TRANSFER_ENTRY` and `unjoin-transfer`,
  echoing `split-line` / `unsplit-line`. This is a correction of one line,
  not the rejected suggest-and-confirm workflow.
- **The mirror window is 3 days** (2026-11-14). It covers settlement delay
  both for SEPA transfers and for transfers from abroad.
- **No separate fee line** (2026-11-14). The user's statements carry no
  separate fee line for a remittance, so in v1 one euro line is the whole
  of X, fee included, as `multi-currency-and-fx` requires.
- **The reverse remittance is in scope** (2026-11-14). A remittance rule may
  match in the incoming direction, with the same pending-then-complete
  shape. It completes to the reverse two-amount entry of issue 115.
- **One spec** (2026-11-14). The transfer slices land first, the remittance
  slices (both directions) after.

## Requirements

Each item below is the brief's recommendation, adopted as the default.
**Every item in this section is a recommended default, not yet confirmed by
the user.** The user confirms or changes them on review, before freezing.

- **Rule syntax** (recommended default, not yet confirmed by the user).
  - A transfer or remittance rule uses an explicit action key distinct from
    `account`, naming the counterpart. A remittance rule also names the
    currency unit. The matched line's sign gives the direction (outgoing or
    incoming), and the existing `direction` condition (`"in"` / `"out"`)
    restricts a rule to one of them.
  - Kohle never infers the kind from the target's account type. Doing so
    would silently turn existing rules that target an asset clearing account
    into transfer rules.
  - The kind and the unit are part of the rule's content identity, so
    changing either retires the rule.
- **Allowed counterparts** (recommended default, not yet confirmed by the
  user).
  - Any leaf asset or liability account outside the People branch. That
    covers a credit-card liability paid from Checking, which overlaps
    `debts-and-liabilities`.
  - Applying the rule file fails, and names the rule, when a counterpart is
    any of these:
    - an expense or income account;
    - an unclassified bucket or the pending bucket;
    - a People account;
    - the importing account itself.
- **Mirror recognition** (recommended default, not yet confirmed by the
  user; the 3-day window is the user's).
  - When a row is imported into account B, it is the mirror of a transfer
    already posted from account A when all of these hold:
    - the transfer's counterpart is B and it has no mirror yet;
    - the row goes in the opposite direction;
    - the amount is exactly equal;
    - the row's date is at most 3 calendar days before or after the
      transfer's date.
  - If A has an IBAN and the row has a counterparty IBAN, they must also
    match.
  - The check runs before the rules, so no rule can also classify a mirror.
  - Absorbing a mirror posts no second move. The row's native reference is
    still recorded, so re-import writes nothing.
  - With several candidates (two 500 transfers in one week), pairing is
    nearest date first, and deterministic.
- **Import order** (recommended default, not yet confirmed by the user).
  - Matching is symmetric. Whichever row arrives second is absorbed into the
    move the first one made.
  - If Savings is imported first, its +500 is matched by an inbound transfer
    rule on Savings, or falls through to `Unclassified Income`. When the first
    row was a fall-through and the second matches a transfer rule, the move is
    posted and the fall-through is cancelled by an adjusting entry, in the same
    import.
  - The move carries the date of whichever side posted it. Balances agree
    once both rows are in, so the move is not re-dated to the outgoing side.
- **A mirror that is missing or late** (recommended default, not yet
  confirmed by the user).
  - A counterpart that has never had a statement imported expects no mirror.
  - On an imported counterpart, a missing mirror is not an error. A mirror
    outside the window falls through to its bucket and shows in
    `list-unclassified`. The join correction (Decisions) can then join it.
  - A read-only listing shows transfers still without a mirror, limited to
    counterparts that have had a statement imported.
  - `reclassify` onto an own account goes through the same transfer path,
    instead of double counting or being refused.
- **Pending remittance** (recommended default, not yet confirmed by the
  user).
  - A remittance rule posts the line between the euro account and a pending
    bucket. The bucket is an own asset account, created on first use like
    the unclassified buckets.
  - Outgoing: net worth counts the euros in transit at face value until
    completion.
  - Incoming: the euros received are offset by the pending bucket, and the
    INR stays on the counterpart until completion. Nothing is counted twice.
  - The line's classification records the counterpart, the unit and the
    direction.
  - Pending remittances are listed, in both directions.
- **Completion** (recommended default, not yet confirmed by the user).
  - A completing command takes the entry id and Y. It posts an adjusting
    entry in the two-amount form, dated at the original line, as
    `reclassify` dates its reversing pair. Order-independence from
    `multi-currency-and-fx` covers the backdating.
  - Outgoing: it takes X EUR out of the pending bucket and puts Y of the unit
    into the counterpart. The rate is derived as X / Y, and the lot costs
    exactly X. FIFO sees the lot on the day the euros left.
  - Incoming: it takes Y of the unit out of the counterpart, consuming lots
    FIFO, and clears X EUR from the pending bucket. The FX gain is realised
    as issue 115 defines. A shortfall of lots fails as that spec requires
    and writes nothing.
  - Completion is shaped so that a later Indian bank importer can call it
    when its currency row is the remittance's mirror. How that row is
    matched is for that importer's brief.
- **Rule priority, retirement and re-apply** (recommended default, not yet
  confirmed by the user).
  - Transfer and remittance rules are ordinary entries in the one ordered
    list, and the first match wins. Mirror recognition runs before any rule.
  - Retiring or editing a transfer or remittance rule never undoes a posted
    move. As today, only `classify-rules` moves anything.
  - `classify-rules` applies transfer and remittance rules to fall-through
    lines. A transfer move also absorbs the counterpart's fall-through
    mirror in the same run, and the preview shows both lines. It never
    touches lines a rule or a human already classified.
- **Corrections** (recommended default, not yet confirmed by the user). Each
  is all or nothing, by adjusting entry.
  - **A wrong transfer.** `reclassify` of a transfer line to a category
    reverses the move and un-absorbs its mirror in the same operation. The
    mirror goes back to its bucket.
  - **A wrong pairing.** Un-absorbing a mirror reinstates the row's own
    posting.
  - **A wrong Y.** The completion is reversed and redone.
  - **Split-line.** `split-line` is refused on a transfer line, an absorbed
    mirror and a pending remittance.
  - None of this depends on `undo-delete-edit`. It stays in this spec.
- **Classification records** (recommended default, not yet confirmed by the
  user).
  - The records must tell these apart:
    - a rule-made transfer;
    - an absorbed mirror, which names the move it joined;
    - a pending remittance, then the same remittance completed, in either
      direction;
    - a human correction.
  - `proposed_account_id` keeps pointing where the import put the line,
    because `reclassify` and `split-line` find the original line through it.
- **Docs examples** (recommended default, not yet confirmed by the user).
  - A second fictional statement (Savings, in the same Deutsche Bank format)
    with the mirror row.
  - A fictional remittance-service card payment on Checking, and a fictional
    euro inflow for the reverse remittance.
  - INR as the unit, as `multi-currency-and-fx` documents only INR, with a
    fictional `IndianBank` account and fictional amounts.

### Left to the architect

The brief gave no recommendation for these. The architect decides them in
the design:

- the pending bucket's name;
- command names: the completion, the listing of transfers awaiting a mirror,
  and the final names of the join correction (`cli-command-naming` may
  rename them later);
- whether pending remittances show in `list-unclassified` or in a listing of
  their own;
- the rule-file key names;
- the classification record shape, and how an absorbed row is stored;
- where the mirror lookup runs, given that `match_rule` stays pure and
  session-free and no second transaction is opened.

## Goals

- **Transfers count once.** Once a transfer rule is in place, a transfer
  between two own accounts whose statements are both imported appears as a
  single move. It leaves nothing in any expense, income or unclassified
  account. Each account's balance equals its statement.
  - Testable: Checking's statement has −500.00 to Savings on 2026-04-03, and
    Savings' statement has +500.00 from Checking on 2026-04-04. With a
    transfer rule, importing both leaves one 500.00 transfer from Checking to
    Savings. No expense, income or unclassified account holds any of it, and
    `list-unclassified` does not show it. Balances are the same whichever
    statement is imported first. The move is dated 2026-04-03 when Checking
    is imported first, and 2026-04-04 when Savings is.
  - Testable: a mirror dated 3 days after the transfer is absorbed. One dated
    4 days after falls through to its bucket.
  - Re-importing either statement writes nothing. Dedup stays per account by
    native reference.
- **A counterpart that is never imported is fine.** A transfer to an own
  account with no importer (cash, the Indian bank today) is one move, and
  kohle expects no mirror for it.
- **A remittance becomes a lot at the euros sent.** A euro line matched by a
  remittance rule ends up as the two-amount entry of `multi-currency-and-fx`.
  X is the euros debited on the line. Y is the currency received. The rate is
  derived as X / Y and never typed, and the lot costs exactly X.
  - Testable: a 1,012.00 EUR card payment matched by a remittance rule whose
    counterpart is IndianBank, once Y = 90,000 INR is supplied, gives one INR
    lot on IndianBank costing exactly 1,012.00 EUR. Nothing for it remains in
    an unclassified bucket or a pending state.
- **Changing back realises the FX gain.** A euro inflow matched by an
  incoming remittance rule ends up as the reverse two-amount entry of issue
  115.
  - Testable: IndianBank holds one 90,000 INR lot costing 1,012.00 EUR. A
    1,100.00 EUR inflow on Checking matched by an incoming remittance rule
    whose counterpart is IndianBank, once Y = 90,000 INR is supplied,
    consumes that lot and shows 88.00 EUR realised gain under unit `INR` in
    `realised`. Nothing for it remains pending.
- **Recording still never reads a fetched price or rate.** Neither a transfer
  nor a remittance takes a euro figure from `prices`.
  `tests/test_price_guards.py` holds for every new path.
- **Every classification stays recorded.** A transfer, an absorbed mirror and
  a pending or completed remittance are each distinguishable in the
  classification records. None of them can be mistaken for a category
  classification or for a human correction, because these records are the
  training labels for the later ML phase.
- **All-or-nothing.** An import, a `classify-rules` run, a correction and a
  remittance completion each apply fully or leave the ledger untouched. Each
  one that writes is one audit-trail group.
- **No regressions.** A ledger whose rules have no transfer or remittance
  action gives exactly today's output from every command. Existing rules,
  including ones that already name an asset account such as a `Transfers`
  clearing account, keep their meaning.
- **Docs.** `import-and-classification.md`, and `recording-entries.md` for
  the remittance, are updated in the same PRs as the behaviour. Examples use
  fictional accounts, counterparties, IBANs and amounts, and run as checked
  `console` blocks.

## Non-Goals

- A pairing command that suggests matches for the user to confirm, and any
  pairing done without a rule.
- The Indian bank and demat importers. They remain follow-up briefs, as
  `multi-currency-and-fx` says, and `CashRow` stays base-currency only. This
  spec must not foreclose their rows later completing a pending remittance.
- Kohle supplying Y, or a rate, from a fetched price.
- A remittance fee posted as a separate statement line. The user's
  statements have none, so one line is the whole of X.
- Transfers between two own accounts in different non-base currencies (no
  conversion chains, as in `multi-currency-and-fx`).
- A transfer whose two sides differ in euro amount. The only case with
  differing amounts is a remittance.
- People accounts as counterparts. Money to or from a person stays with
  `split-line` and the People branch.
- Changes to dedup (issue 026) or to the importer contract.

## Technical Approach

- Python 3.12, `uv`, the layering and `Result` values in `AGENTS.md`.
- **Builds on the rule file.** The rule file format, condition trees,
  content-based identity, `classify-rules` and `classifications.rerun_rule_id`
  come from `complex-classification-rules`. That spec is frozen and
  implemented (PR #17, issues 082 to 089). `retire-quick-rule-commands` is
  done too, so the file is the only way to manage rules. This spec adds an
  action kind to `[[rule]]`; conditions are unchanged.
- **Builds on `multi-currency-and-fx` for the remittance half.** It needs the
  two-amount entry and currency-unit lots (issue 111), the reverse entry that
  realises FX gain (issue 115), and currency moves with fail-fast (issue
  117). That spec is implemented and merged (PR #23), so neither half waits
  on anything.
- **Slice order.** One spec. The transfer slices come first, then the
  remittance slices, outgoing then incoming.
- **Placement.** Item 3 in the agreed brief order, after
  `multi-currency-and-fx` and before `undo-delete-edit`, inside the
  pre-January cut line. `dev/roadmap.md` does not list this spec, and still
  lists `complex-classification-rules` as item 8 although it has landed.
  Updating the roadmap is the user's call.
- **Places this touches.** `match_rule` and the import loop in
  `ImportStatement.execute` (`kohle/use_cases/journal.py`).
  `kohle/use_cases/classification.py` (reclassify, split-line,
  classify-rules). Rule-file validation in `kohle/use_cases/rules.py`. The
  `Classification` model. The two-amount recording path, both directions.
  `match_rule` stays pure and session-free.
- **Own accounts may carry an IBAN** (`accounts.iban`, unique, set by
  `add-account --iban`). Mirror recognition uses it when both sides have one.
- **Testing.** Recommended default, not yet confirmed by the user.
  - Mirror matching is a pure function, tested without a session:
    - the 3-day window edges;
    - exact amount;
    - the IBAN check;
    - several candidates;
    - a row that must not be absorbed.
  - End to end through `import-statement` with fixture statements:
    - both import orders;
    - re-import;
    - a mirror outside the window;
    - a counterpart never imported;
    - a crash part-way through an import, which leaves nothing written and
      no audit-trail group.
  - An outgoing remittance completes to a lot of exactly X. An incoming one
    realises the gain from issue 115.
  - Rule files without the new action give unchanged output.

## Open Questions

- The user should confirm or change each recommended default in
  Requirements, and the testing approach above, before freezing.
- The decisions listed under "Left to the architect" are made in the design,
  not here.

Nothing else is open.
