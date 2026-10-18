# Richer classification rules

## Goal

Let a classification rule express what a person actually knows about a
recurring payment — who it goes to, how much, in which direction — not just
what text it contains, so that fewer lines fall into the unclassified buckets
and fewer land in a plausible but wrong category.

The problem behind it: a rule today is one regular expression and a target
account. The motivating case is sending a partner money every month. One
payment is a shared household expense and another is an investment into their
account. If the reference text differs, two priority-ordered rules already
separate them. If the text is identical and only the amount differs (a monthly
500 and a one-off 2000), nothing can tell them apart, and the user is left to
fix each odd line with `reclassify`.

## Considerations surfaced

**What a rule can see today.** `match_rule` in `kohle/use_cases/rules.py` tests
one pattern against the description, the counterparty name and the counterparty
IBAN, and matches if any one of them hits. The first match by priority wins.
There is no condition on amount, direction (money in or out), or date, and no
way to require two things at once. Direction also cannot choose the target:
the counterpart leg's sign comes from the line, so the same IBAN's incoming and
outgoing payments cannot go to different accounts.

**Conditions as columns, ANDed.** Proposed direction: a rule carries optional
per-field conditions — a pattern on the description, a pattern on the
counterparty name, an exact IBAN, an amount range, a direction — and matches
when every condition it has holds. An existing rule becomes "this pattern on
any field", today's behaviour unchanged. The partner case is two rules: the
same IBAN with two amount ranges. Alternatives that OR conditions are already
expressible as two priority-ordered rules.

**First-match-wins and priority stay.** Existing rules, `list-rules` and
`remove-rule` depend on them.

**Rules stay immutable.** `Classification` rows record the `rule_id` that
matched. An editable rule would leave history pointing at a rule that now
means something else. A change is remove and add, as today.

**Matching stays pure.** `match_rule` is a session-free function — a line in, a
rule or nothing out — and is called inside the import loop. Richer conditions
keep it that way; the line's amount and direction are already known there.

**The rule engine is also data collection.** A learned classifier is not part
of this work, but is the expected later step. Every classification is recorded
in `Classification` (what was proposed, by which rule, and where the line
ended up), and `reclassify` records corrections. Over time that, plus manually
tagging statements from past years, becomes labelled data for text
classification. This is a reason to keep the classification and correction
records complete and accurate, not a feature to build now.

**The CLI shape.** `add-rule` takes a pattern and an account today. Several
optional conditions mean several optional flags; the names fall under
`cli-command-naming`.

## Directions rejected

- **A small expression language for conditions**: a parser, an error-message
  surface, and CLI quoting problems, to express ORs that two rules already
  cover.
- **Editable rules**: they rewrite the meaning of recorded classifications.
- **A machine-learning classifier now**: without enough labelled data, a model
  adds more noise than benefit, and is less accurate than explicit rules.
  Revisit once the rule engine and manual tagging have produced enough data;
  then it is a text-classification problem.
- **A classifier plugin contract**: a contract designed around one
  implementation tends to be wrong; extract it if a second classifier ever
  exists.
- **Solving the partner case by IBAN alone**: it is the case this brief exists
  for, and IBAN alone cannot separate it.

## Open questions

- Which conditions are in the first version: amount equality, amount range,
  direction, separate description/counterparty/IBAN fields, day of month?
- Is an amount range inclusive, and is it on the absolute amount with
  direction as a separate condition?
- Should direction alone be able to pick a different target for the same
  counterparty?
- Do existing rules need a migration, or is the "any field" pattern kept as a
  distinct condition?
- How does `list-rules` display a rule with several conditions readably?
