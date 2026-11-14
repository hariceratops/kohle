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

**A remittance paid from a euro account.** A remittance paid by card or by
transfer is imported as a euro spend on Checking. There is no INR row to pair
it with, because the Indian bank importer is a Non-Goal of
`multi-currency-and-fx`. Nor is there any way to turn an imported line into
the two-amount form that spec defines (`record ... --to-unit INR --total X`),
which creates an INR lot at the euros actually sent.

This brief extends classification rules so that one rule kind covers both
cases.

## Decisions (made by the user)

- **Rules, not a pairing workflow.** Both cases are handled by
  classification rules. There is no separate suggest-and-confirm pairing
  command, and no automatic merge at import that runs without a rule.
- **A transfer rule targets an own account.** Its action names an own account
  (the counterpart) instead of an expense or income category. A matching line
  becomes a move between the two own accounts.
- **A remittance rule is a transfer-style rule.** Its counterpart is the own
  account that receives a non-base currency (INR). As in
  `multi-currency-and-fx`, the mechanism applies to any non-base currency
  unit, and no code names INR.
- **Corrections and undo use adjusting entries**, as classification does
  today (issue 017, `reclassify`, `classify-rules`). The ledger stays
  append-only: nothing is edited, voided or deleted, and the audit trail
  keeps every step.

## Goals

- **Transfers count once.** Once a transfer rule is in place, a transfer
  between two own accounts whose statements are both imported appears as a
  single move. It leaves nothing in any expense, income or unclassified
  account. Each account's balance equals its statement.
  - Testable: Checking's statement has −500.00 to Savings on 2026-04-03, and
    Savings' statement has +500.00 from Checking on 2026-04-04. With a
    transfer rule, importing both leaves one 500.00 transfer from Checking to
    Savings. No expense, income or unclassified account holds any of it, and
    `list-unclassified` does not show it. The result is the same whichever
    statement is imported first (see Open Questions for the entry date).
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
  brief must not foreclose their rows later completing a pending remittance
  (see Open Questions).
- Kohle supplying Y, or a rate, from a fetched price.
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
  done too, so the file is the only way to manage rules. This brief adds an
  action kind to `[[rule]]`; conditions are unchanged. `dev/roadmap.md` still
  lists `complex-classification-rules` as item 8 ("editor-driven rules with
  column conditions"). That work has landed, so the dependency is already met
  and this brief waits on nothing from it. The roadmap entry looks stale, and
  updating it is the user's call.
- **Depends on `multi-currency-and-fx` for the remittance half.** That half
  needs the two-amount entry and currency-unit lots (issue 111), and currency
  moves with fail-fast (issue 117). The transfer half depends on neither and
  can land first.
- **Places this touches.** `match_rule` and the import loop in
  `ImportStatement.execute` (`kohle/use_cases/journal.py`).
  `kohle/use_cases/classification.py` (reclassify, split-line,
  classify-rules). Rule-file validation in `kohle/use_cases/rules.py`. The
  `Classification` model. The two-amount recording path. `match_rule` stays
  pure and session-free. The mirror lookup reads existing entries, so the
  design decides where it runs without opening a second transaction.
- **Own accounts may carry an IBAN** (`accounts.iban`, unique, set by
  `add-account --iban`). Mirror recognition can use it (see Open Questions).

## Open Questions

Each question gives a recommendation where there is one. None of them is
decided.

1. **How a rule says "transfer" and "remittance" in the file.**
   - Inferring the kind from the target's account type would silently turn
     existing rules that target an asset clearing account into transfer
     rules.
   - Accounts are multi-unit, so "an INR own account" is not a property of
     the account. A remittance rule must name the currency unit received.
   - Recommendation: an explicit action key distinct from `account`, naming
     the counterpart. A remittance adds the currency unit. The design picks
     the key names. Both the kind and the unit are part of the rule's content
     identity, so changing either retires the rule.
2. **Which accounts may be a counterpart.**
   - Recommendation: any leaf asset or liability account outside the People
     branch. That covers a credit-card liability paid from Checking, which
     overlaps `debts-and-liabilities`.
   - Refuse, when the file is applied:
     - expense and income accounts;
     - the unclassified buckets and the pending bucket (question 6);
     - People accounts;
     - a counterpart that is the importing account itself.
3. **How the mirror row is recognised and absorbed without double counting.**
   - Recommendation: when a row is imported into account B, it is the mirror
     of a transfer already posted from account A when all of these hold:
     - the transfer's counterpart is B and it has no mirror yet;
     - the row is in the opposite direction;
     - the amount is exactly equal;
     - the date is within a window of the transfer's date (a few days; the
       user to set it).
   - If A has an IBAN and the row has a counterparty IBAN, they must also
     match.
   - The check runs before the rules, so no rule can also classify a mirror.
   - Absorbing a mirror posts no second move, but the row's native reference
     is still recorded, so re-import stays a no-op.
   - With several candidates (two 500 transfers in one week), pair them
     nearest date first, deterministically.
   - How the absorbed row is stored is the architect's decision.
4. **The order the two statements are imported in.**
   - If Savings is imported first, its +500 is either matched by an inbound
     transfer rule on Savings, or it falls through to `Unclassified Income`.
   - Recommendation: matching is symmetric. Whichever row arrives second is
     absorbed into the move the first one made.
   - When the first was a fall-through and the second matches a transfer
     rule, the move is posted and the fall-through is cancelled by an
     adjusting entry, in the same import.
   - The entry date differs by order (the outgoing side's 3 April or the
     incoming side's 4 April). Recommendation: accept the date of whichever
     side posted the move, since balances agree once both are in. The
     alternative is always the outgoing side's date, which would need the
     move re-dated by adjusting entries.
5. **What happens when the mirror never arrives, or arrives outside the
   window.**
   - A counterpart that has never had a statement imported expects no mirror
     (Goals).
   - On an imported counterpart, a missing mirror is not an error. A mirror
     outside the window falls through to its bucket, where
     `list-unclassified` shows it.
   - Recommendation: a read-only listing of transfers still without a mirror
     on counterparts that have had a statement imported.
   - Decided: a correction that joins a named fall-through line to a named
     transfer by adjusting entry, as `reclassify` corrects a line. That is a
     correction of one line, not the suggest-and-confirm workflow the user
     rejected, and the user has accepted it.
   - Name: `join-transfer LINE_ENTRY TRANSFER_ENTRY`, with `unjoin-transfer`
     to reverse it, echoing `split-line` / `unsplit-line`. "Absorb" is
     internal wording only; it names no command. Final naming follows
     `cli-command-naming`.
   - `reclassify` onto an own account then goes through the same transfer
     path instead of double counting. The alternative is to refuse it.
6. **What state a remittance line is left in before Y is known.**
   - Recommendation: the rule posts the line from Checking into a pending
     bucket. The bucket is an own asset account, created on first use like
     the unclassified buckets, and its name is open.
   - Net worth then counts the euros in transit at face value until
     completion.
   - The line's classification records the counterpart and the unit.
   - Pending remittances are listed, either in `list-unclassified` or in a
     listing of their own. Which one is open.
7. **How Y is supplied.**
   - Recommendation: a completing command takes the entry id and Y. It posts
     an adjusting entry that takes X EUR out of the pending bucket and puts Y
     of the unit into the counterpart, in the two-amount form. The lot then
     costs exactly X and the rate is derived.
   - It is dated at the original line, as `reclassify` dates its reversing
     pair, so FIFO sees the lot on the day the euros left. Order-independence
     from `multi-currency-and-fx` covers the backdating.
   - Later, a currency row from the Indian bank importer arriving on the
     counterpart would be that remittance's mirror. Absorbing it would
     complete the remittance with the row's Y. Its matching can only use
     direction, date window and counterpart (the amounts are in different
     currencies), so it is a design question for that importer's brief.
     Recommendation: shape the completion so that this importer can call it
     later.
8. **Fees.**
   - `multi-currency-and-fx` says X includes the fee and that the fee becomes
     part of the INR lot's cost. Recommendation: in v1 one euro line is the
     whole X.
   - If the user's bank posts the fee as a separate line, the options are:
     - a rule routes the fee line to the same pending remittance, and
       completion takes the sum of its lines as X;
     - the fee is booked as an expense, which departs from the
       multi-currency rule.
   - The user to say whether real statements carry a separate fee line.
     Support it only if they do.
9. **Changing euros back from INR.** Rupees changed back arrive as a euro
   inflow on Checking. They are the inverse remittance of
   `multi-currency-and-fx` (issue 115), which consumes INR lots FIFO and
   realises FX gain. Recommendation: allow a remittance rule in the `in`
   direction with the same pending-and-complete shape. If that is not wanted,
   list it as a Non-Goal.
10. **Rule priority, retirement and re-apply.**
    - Recommendation: transfer and remittance rules are ordinary entries in
      the one ordered list, and the first match wins. Mirror absorption
      (question 3) runs before any rule.
    - Retiring or editing a transfer rule never undoes a posted move. As
      today, only `classify-rules` moves anything.
    - `classify-rules` applies transfer rules to fall-through lines. A move
      also absorbs the counterpart's fall-through mirror in the same run, and
      the preview shows both lines. It still never touches lines a rule or a
      human already classified.
11. **Corrections and undo, by adjusting entry.** Each of these is all or
    nothing:
    - **A wrong transfer.** `reclassify` of a transfer line to a category
      reverses the move, and un-absorbs its mirror in the same operation. The
      mirror goes back to its bucket.
    - **A wrong pairing.** Un-absorbing a mirror reinstates the row's own
      posting.
    - **A wrong Y.** The completion is reversed and redone.
    - **Split-line.** Recommendation: refuse `split-line` on a transfer line,
      an absorbed mirror and a pending remittance.
    - Whether this overlaps `undo-delete-edit` is open. Recommendation: it
      does not depend on that brief, and stays in this one.
12. **Classification records.**
    - The record shape is the architect's decision. Whatever it is must tell
      apart:
      - a rule-made transfer;
      - an absorbed mirror, which names the move it joined;
      - a pending remittance, then the same remittance completed;
      - a human correction.
    - `proposed_account_id` must keep pointing where the import put the line,
      because `reclassify` and `split-line` find the original line through
      it.
13. **Docs examples.**
    - Docs need a second fictional statement (Savings, in the same Deutsche
      Bank format) with the mirror row.
    - They need a fictional remittance-service card payment on Checking.
    - Examples use INR, as `multi-currency-and-fx` does ("only INR is
      documented with examples"), with fictional accounts (`IndianBank`) and
      amounts. If "fictional units" was meant as a made-up currency code
      instead, the user should say so.
14. **Testability.**
    - Mirror matching is a pure function, tested without a session:
      - window edges;
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
    - The remittance completes to a lot of exactly X.
    - Rule files without the new action give unchanged output.
15. **Placement.** This brief is not in the agreed brief order or in
    `dev/roadmap.md`. Where it goes, and whether it is one spec or two (the
    transfer half could land before the remittance half), is the user's
    call. Recommendation: one spec, with the transfer slices first and the
    remittance slices after issues 111 and 117.
