# [feat] Import absorbs the mirror row of a transfer

When the counterpart's own statement is imported, its row is recognised as the mirror of the transfer already posted and absorbed into it, so the transfer counts once whichever statement arrives first. Depends on 126.

## Acceptance Criteria

- Mirror recognition is a pure function tested without a session. A row imported into B is the mirror of a transfer from A when: the transfer's counterpart is B and it has no mirror yet; the row goes the opposite way; the amount is exactly equal; the row's date is at most 3 calendar days before or after the transfer's date (inclusive).
- When A has an IBAN and the row has a counterparty IBAN, they must also match.
- With several candidates, pairing is nearest date first and deterministic.
- The check runs before the rules, so no rule can also classify a mirror.
- Absorbing posts no second move; the row's native reference is still recorded, so re-importing either statement writes nothing.
- Checking −500.00 on 2026-04-03 and Savings +500.00 on 2026-04-04, with a transfer rule, leaves one 500.00 transfer, nothing in expense, income or unclassified accounts, and nothing in `list-unclassified`. Balances are the same in both import orders. The example has two rules, Checking outbound and Savings inbound; the move is dated 2026-04-03 when Checking is imported first and 2026-04-04 when Savings is (the date of whichever side posted the move).
- An absorbed row is posted as its normal fall-through and moved onto its own account by an adjusting entry in the same transaction; it leaves a net-zero pair in `entries-in-period`, with balances and listings unaffected.
- The mirror lookup runs inside `ImportStatement`'s own transaction before `match_rule`; `match_rule` only gains a plain `statement_account_id` parameter.
- First commit: the behaviour-neutral module moves (`posting.py`, bucket names to `accounts.py`, old import paths re-exported); then the feature.
- When the first-imported row fell through to a bucket and the second matches a transfer rule, the move is posted and the fall-through is cancelled by an adjusting entry in the same import.
- A mirror dated 3 days after the transfer is absorbed; one dated 4 days after falls through to its bucket and shows in `list-unclassified`.
- An absorbed mirror has its own classification record naming the move it joined.
- A crash part-way through an import leaves nothing written and no audit-trail group.
- `import-and-classification.md` gains the second fictional statement (Savings, Deutsche Bank format) with the mirror row, as a checked `console` example.
- Every existing test passes unchanged.
