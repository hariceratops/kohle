"""Layer 2 — service tests against the `session` fixture.

The recursive descendant query behind `balance` rollup (issue 003).

The cycle test below is the regression guard for a non-obvious property: with
cyclic parentage, UNION projecting only `Account.id` terminates, while UNION
ALL and UNION projecting (id, depth) both hang — a monotonic column makes
every row distinct, so deduplication never fires. Someone adding a depth
column "for display" would turn this query into a hang.

That is also why the cycle test carries a timeout: it guards against a hang,
so a regression makes it block rather than fail, and an unattended run would
never finish.
"""

import pytest
from sqlalchemy.orm import Session


def test_placeholder(session: Session) -> None:
    # TODO: a leaf account's descendant set is itself alone
    # TODO: a parent returns itself plus its direct children
    # TODO: a deep chain (5+ levels) returns every level, not just the first
    # TODO: a wide tree returns all siblings
    # TODO: an unrelated sibling subtree is excluded
    assert True


@pytest.mark.timeout(10)
def test_cycle_placeholder(session: Session) -> None:
    # The cycle is built by setting parent_id directly on committed rows: no
    # use case can create one, so this guards against corrupt data rather than
    # a reachable state. Do not "fix" it by routing through AddAccount.
    #
    # TODO: A -> B -> A terminates and returns the reachable set
    # TODO: a self-parented account terminates
    assert True
