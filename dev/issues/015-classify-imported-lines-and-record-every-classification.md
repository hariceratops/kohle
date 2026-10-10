# [feat] Classify imported lines at import time, recording every classification

`ImportStatement` routes every row to `Unclassified Expense` or
`Unclassified Income` — its own docstring says "choosing a better
counterpart account is the classifier's job". This is that classifier: the
rule matcher runs per row, a match posts to the rule's target account, and a
row matching nothing falls back to the bucket exactly as today.

Recording is in this slice rather than a follow-up, deliberately. The rule
engine is what produces the labelled data a later ML phase would need, and
the spec calls that capture "expensive to retrofit and nearly free to build
in now". A slice that classifies without recording ships precisely the gap
the spec exists to avoid, so the first line ever classified is recorded.

Depends on: 013 (counterparty to match on), 014 (rules to match with)
Spec: `dev/specs/expense-classification.md`

## Acceptance Criteria

- `ImportStatement` runs the rule matcher for every imported row instead of
  unconditionally routing to the unclassified buckets.
- A row matching a rule posts to that rule's target account.
- A row matching no rule posts to `Unclassified Expense` or
  `Unclassified Income` exactly as it does today. Import behaviour with an
  empty rule set is unchanged.
- The matcher matches on description and on counterparty — both the name and
  the IBAN captured in 013.
- A classification record is written for every imported row, on both paths,
  holding: the proposed account, the rule that matched (null when none did),
  the final account, and whether a human has corrected it (false at import).
- The record is written for fall-through rows too, not only matches, so
  there is one place to read from regardless of whether a rule fired.
- Posting still routes through `post_entry`; this slice reimplements neither
  the balance-by-value check nor the leaf-only posting rule.
- Classification writes join the importing entry's operation group rather
  than forming their own — one import row is one logical write.
- Importing the same statement twice still imports nothing the second time:
  duplicate detection is unaffected.
