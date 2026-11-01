# Expected payments

## Goal

Let the user say that a recurring payment is expected (the yearly insurance,
a quarterly fee) and be told when one has not appeared by the time it should
have, such as the insurance not taken by April.

The problem behind it: `budgeting` compares what was spent against a cap per
category and period, but a cap cannot tell "nothing spent because the
payment was dropped" from "nothing spent yet because it is late". Only
knowing the specific payment that was expected can tell those apart.

Split out of `budgeting`, where it was wanted but left out of the first
version. To revisit in 2027.

## Considerations surfaced

**It needs more metadata than a cap.** A cap is an amount over a period for
a category. An expected payment also needs to say which payment counts as
having arrived: roughly when it is due, how late it may be, and how to
recognise it among the category's lines. Recognising it could use the
counterparty, an amount range, or the classification rule that put it there.

**Budgets are estimates, and a payment may be dropped on purpose.** A
missing payment is a prompt to look, not an error. It must be possible to
mark an expected payment as dropped or ended so that it stops flagging.

**One recurrence vocabulary.** When a payment is due is a recurrence. It
uses kohle's single vocabulary (`configurable-net-worth-sampling`, extended
by `budgeting`) and does not define a second one.

**It overlaps with richer classification rules.** `complex-classification-rules`
adds conditions on counterparty, IBAN, amount and direction. Those are the
same facts that recognise an expected payment, so the two may share
matching.

## Directions rejected

- **As a requirement of `budgeting`**: budgets are estimates, and the cap
  report stands without it.

## Open questions

- How an expected payment is recognised among the lines: by counterparty,
  amount range, rule, or account alone.
- Whether it is tied to a cap or stands on its own.
- How late a payment may be before it is flagged, and whether a payment that
  arrives early counts.
- Where flags appear: in the budget report, in a report of their own, or
  after an import.
- How "dropped" or "ended" is recorded, and whether it is effective-dated.
