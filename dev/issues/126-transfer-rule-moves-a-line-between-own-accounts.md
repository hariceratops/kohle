# [feat] A transfer rule moves a line between two own accounts

A rule may name an own account as the counterpart through an explicit action key, so a matched statement line becomes one move between the two accounts instead of an expense or income against a bucket. Spec: `transfer-rules-and-remittance-pairing`.

## Acceptance Criteria

- A `[[rule]]` can carry a transfer action naming the counterpart, using a key distinct from `account`; the architect picks the key name.
- Kohle never infers the kind from the target's account type: an existing rule whose `account` is an asset clearing account such as `Transfers` keeps its meaning.
- Applying the rule file fails, and names the rule, when the counterpart is an expense or income account, an unclassified bucket, the pending bucket, or a People account. A leaf asset or liability account outside People is accepted.
- A transfer rule never matches a row imported into its own counterpart (source equal to destination is not a pair); the next rule is tried. Rules are not scoped to an account.
- Rule keys: exactly one action key per rule, `account` (unchanged) or `transfer`; stored as `rules.kind`, with identity `(when, kind, account, unit)`. A rule file with only `account` rules renders byte-identically.
- First commit: capture the no-regression oracle from pre-feature code.
- Importing a line matched by a transfer rule posts one move between the importing account and the counterpart, and nothing in any expense, income or unclassified account.
- A counterpart that has never had a statement imported is fine: one move, no mirror expected.
- The kind is part of the rule's content identity, so changing it retires the rule.
- The classification record tells a rule-made transfer apart from a category classification and from a human correction; `proposed_account_id` keeps pointing where the import put the line.
- The import is all-or-nothing and is one audit-trail group.
- A ledger whose rules have no transfer action gives exactly today's output from every command.
- `match_rule` stays pure and session-free.
- `import-and-classification.md` is updated with checked `console` examples using fictional accounts, IBANs and amounts.
- Every existing test passes unchanged.
