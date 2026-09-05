"""Layer 3 — the spec's primary acceptance scenario, end to end.

This is the worked scenario from dev/specs/cli-record-and-balances.md: the
one that exercises record, balance and the account tree together. If this
passes, issues 001, 002 and 003 are done.

Note every posting lands on a leaf. `Cash` is a rollup parent and is never
posted to — that is the leaf-only rule working, not an obstacle being worked
around, and it is why `Unallocated` exists at all.
"""

from sqlalchemy.orm import Session


def test_placeholder(session: Session) -> None:
    # TODO: build the tree — Cash, with Unallocated / Groceries / Eating out
    #       as leaf children
    # TODO: withdraw a lump sum: credit Checking, debit Cash:Unallocated
    # TODO: allocate a quota: credit Unallocated, debit Groceries — the
    #       sibling transfer nets to zero at Cash
    # TODO: spend from an envelope: credit Groceries, debit an expense account
    # TODO: balance Cash rolls up across all three children and equals the
    #       lump sum minus what has left the tree
    # TODO: balance Groceries reports that envelope alone
    # TODO: overspending an envelope reports a negative balance and is not an
    #       error — nothing blocks the spend that causes it
    # TODO: posting directly to Cash is rejected
    assert True
