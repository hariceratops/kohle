# Richer classification rules, and a classifier seam for ML

## Goal

Let a classification rule express what a person actually knows about a
recurring payment, not just what text it contains, and leave a clear seam where
a different kind of classifier (a learned model) can be added later.

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

**Rules as data.** Richer conditions are core behaviour, not an extension
point. The open design choice is representation: more columns on the `Rule`
row (amount range, direction, an IBAN field separate from the pattern), or a
small expression language over the line's fields. Whatever is chosen has to
keep first-match-wins and priority, which existing rules, `list-rules` and
`remove-rule` depend on, and old single-pattern rules must keep working
unchanged.

**The classifier seam.** `match_rule` is already a pure function with no
session: a line goes in, and a rule or nothing comes out. A classifier
interface would take the line's features (description, counterparty, amount,
direction, date) and return a proposal (an account, plus a confidence for a
learned model). The rules engine is the built-in implementation. This should be
named in the design but not built as a plugin contract yet: a contract
designed around one implementation tends to be wrong, and the price-fetcher
plugin layer was only justified once two real sources existed. Extract the
contract when a second classifier does.

**Why ML can plausibly fit.** The `Classification` table already records what
was proposed and where the line ended up, and `reclassify` records corrections.
Those rows are labelled data: features, proposal, and the account the user
finally chose.

**Constraints a learned classifier must respect**
- *Reproducibility.* Re-running an import must not change the books. Already
  imported references are skipped and the decision is recorded in
  `Classification`, so a retrained model cannot reclassify history. This must
  stay true.
- *Suggest, not post.* A model probably proposes and a person confirms through
  `list-unclassified`. Explicit user rules take priority over a model's guess.
- *Validation stays in core.* Any proposed account must exist and be postable
  (leaf-only rule), as unknown instruments are refused today. A classifier
  cannot post to a parent account.
- *Where it runs.* A local model versus an external service is a privacy
  question, since the input is bank data.

## Directions rejected

A plugin contract for classifiers now (see above). Solving the partner case by
IBAN alone, which is the case this brief exists for.

## Open questions

- Are conditions columns on `Rule` or an expression language? How is a rule
  with several conditions written on the CLI (`add-rule` currently takes a
  pattern and an account)?
- Which conditions are first-version: amount equality, amount range, direction,
  a separate IBAN field, day of month?
- Should direction pick a different target account for the same pattern?
- Do existing rules need migration, or does a plain pattern stay the
  one-condition special case?
- Is an unclassified line the only place a model's suggestion appears, or can it
  also challenge a rule's match?
- What would the training and evaluation loop look like, and who owns the
  model's lifecycle?
