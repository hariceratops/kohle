# Debts and liabilities

## Goal

Let kohle carry debt — a housing mortgage, a credit card balance — so that net
worth stays a true figure when debt exists, and every payment towards it is
split correctly between what is spent and what is repaid.

The problem behind it: the household is debt free today, but that is not
fixed. A mortgage or a credit card bill can arrive, and both change net worth.
The worry raised is that a mortgage, being a liability, makes net worth
negative.

Sequencing: this is planned as the last implementation of the current
inbox — needed only once debt actually appears.

## Considerations surfaced

**The ledger already has liabilities.** `AccountType.liability` exists, and the
net-worth partition already includes asset and liability accounts
(`kohle/use_cases/journal.py`, the own-accounts partition). What is missing is
the modelling around them, not the account type.

**A mortgage does not by itself make net worth negative.** Net worth goes
negative only if the house is left off the books. Buying a house with a 400k
loan adds a 400k asset beside the 400k liability; net worth barely moves. What
is owned is the equity — the house's value minus the remaining loan — and each
principal repayment moves money from cash into that equity.

**The purchase costs are a real, honest dip.** German side costs (land
transfer tax, notary, land registry, possibly an agent) are roughly 10% of the
price. They are spent, not converted into the house, so net worth drops by
that much on the purchase date. That is the true cost of buying and should not
be hidden.

**The house needs a value.** There is no price feed for a house. It is valued
at cost, or at a manual valuation through the existing file price plugin, and
marked as an estimate the way `no price (at cost)` already marks one.

**An installment is part expense, part repayment.**

- Interest is an expense: the price of borrowing.
- Principal is not an expense: cash goes down and the liability goes down by
  the same amount; net worth is unchanged. It is a transfer.
- In an annuity loan the installment is fixed while the split moves: interest
  shrinks as the debt shrinks, so more of each installment is principal over
  time. Example: 400k at 3.5% with a 1,500 installment starts at about 1,167
  interest and 333 principal.
- A special repayment (Sondertilgung) is pure principal.

The bank statement shows one line per installment. A classification rule
cannot split an amount today, so the split comes either from the loan's
amortisation schedule or from the lender's yearly statement used to correct
it.

**Credit cards and double counting.** The card is a liability. Purchases on
it are expenses; paying the card bill from the checking account is a transfer
to the card account, not an expense. If both the card statement and the bank
statement are imported, the bill payment must be classified as that transfer,
or every card purchase is counted twice. A card statement needs an importer
plugin.

**Liquid net worth.** Beside net worth, a second total excluding the house and
its mortgage shows what could actually be spent. Proposed, not agreed.

**Cash flow versus expense.** The installment leaves the account in full
(1,500), but the expense is only the interest (1,167 and falling). A spending
cap sees only the interest, while affordability depends on the whole
installment. This is a cash-flow view distinct from the expense view; see
`budgeting`.

## Directions rejected

- **Treating the whole installment as an expense**: overstates spending and
  never shows the debt shrinking.
- **Leaving the house off the books while carrying the mortgage**: produces
  the misleadingly negative net worth this brief started from.
- **Amortising the purchase costs into the house's value**: hides a real loss
  on the purchase date.

## Open questions

- Is the installment split computed from the loan's terms (rate, installment,
  start), entered per payment, or corrected from the lender's yearly
  statement?
- Is the house a unit with a price (valued through the file plugin), or an
  account recorded at a fixed amount?
- Does `net-worth` show liquid net worth as a second total, or is it a
  separate report?
- How are interest-rate resets at the end of a fixed-rate period
  (Zinsbindung) represented?
- Which credit card statements need importing, and in what format?
- Does budgeting need a cash-flow view alongside the expense view?
