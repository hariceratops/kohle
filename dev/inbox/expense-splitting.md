# Expense splitting

## Goal

Splitwise-style shared expenses: record that a bill was shared, track what each
person owes or is owed, and settle up — using people as accounts rather than a
separate subsystem.

The problem behind it: shared expenses distort a personal ledger. An €80 dinner
where €48 belongs to someone else is not an €80 expense, and without somewhere
to put the other person's share, either the expense totals are wrong or the
transaction has to be excluded and the money goes missing.

## Considerations surfaced

A person is an account. When they owe you it is a receivable, when you owe them
it is a liability, and both already exist as account types. Splitting a bill is
then one entry with lines against several accounts — no new mechanism, and it
composes with everything else for free.

Settlement falls out of the same model: when someone pays you back, that is a
transfer from their account to a cash account, and their balance returns to
zero.

This is explicitly optional and deferrable. Nothing in the ledger, importer,
pricing, reporting or classification work depends on it, so it can land whenever
it becomes interesting without costing anything to postpone. It is written down
here so the ledger design does not accidentally foreclose it.

## Directions rejected

A separate splitting subsystem alongside the ledger — the same mistake as the
parallel instrument ledger, and avoided the same way.

## Open questions

- Do people accounts live in the same tree as financial accounts, or in a
  separate branch of it?
- Is there a concept of a group or a shared trip, or only running per-person
  balances?
- How does a split expense enter — is it always manual, or can an imported line
  be split after the fact?
- Does net worth reporting count money owed to you, and should that be
  separable from actual assets?
- What happens when a split involves a currency you do not hold?
