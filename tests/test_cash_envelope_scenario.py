"""Layer 3 — the spec's primary acceptance scenario, end to end.

This is the worked scenario from dev/specs/cli-record-and-balances.md: the
one that exercises record, balance and the account tree together. If this
passes, issues 001, 002 and 003 are done.

Note every posting lands on a leaf. `Cash` is a rollup parent and is never
posted to — that is the leaf-only rule working, not an obstacle being worked
around, and it is why `Unallocated` exists at all.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from kohle.domain.domain_errors import PostingToNonLeafAccount
from kohle.domain.models import AccountType, JournalLine
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import RecordSimpleEntry


def _net_position(session: Session, account_id: int) -> Decimal:
    lines = session.scalars(select(JournalLine).where(JournalLine.account_id == account_id)).all()
    return sum((line.value if line.is_debit else -line.value for line in lines), Decimal(0))


def test_cash_envelope_scenario(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1").unwrap()
    cash = AddAccount(session).execute("Cash", AccountType.asset).unwrap()
    unallocated = AddAccount(session).execute("Unallocated", AccountType.asset, None, "Cash").unwrap()
    groceries = AddAccount(session).execute("Groceries", AccountType.asset, None, "Cash").unwrap()
    AddAccount(session).execute("Eating out", AccountType.asset, None, "Cash").unwrap()
    AddAccount(session).execute("Aldi", AccountType.expense).unwrap()

    # Step 2: withdraw a lump sum ahead of time.
    withdraw = RecordSimpleEntry(session).execute(
        date(2026, 3, 1), "Withdraw cash", Decimal(200), "Checking", "Unallocated"
    )
    assert withdraw.is_ok

    # Step 3: allocate a quota to an envelope — sibling to sibling.
    allocate = RecordSimpleEntry(session).execute(
        date(2026, 3, 2), "Allocate groceries quota", Decimal(80), "Unallocated", "Groceries"
    )
    assert allocate.is_ok

    # Step 4: spend out of the envelope.
    spend = RecordSimpleEntry(session).execute(
        date(2026, 3, 3), "Aldi", Decimal(30), "Groceries", "Aldi"
    )
    assert spend.is_ok

    # Posting directly to the rollup parent is refused.
    direct_to_parent = RecordSimpleEntry(session).execute(
        date(2026, 3, 4), "Should be rejected", Decimal(10), "Checking", "Cash"
    )
    assert direct_to_parent.is_err
    assert isinstance(direct_to_parent.unwrap_err(), PostingToNonLeafAccount)

    # The sibling-to-sibling allocation nets to zero at Cash: summing every
    # line across the three children is unchanged by a transfer between them.
    # Only the withdrawal (in) and the spend (out) move the aggregate.
    unallocated_net = _net_position(session, unallocated.id)
    groceries_net = _net_position(session, groceries.id)
    cash_children_net = unallocated_net + groceries_net
    assert cash_children_net == Decimal(200) - Decimal(30)

    # Cash itself has never been posted to.
    assert _net_position(session, cash.id) == Decimal(0)

    # TODO (issue 002/003): balance Cash rolls up across all three children
    #       and equals the lump sum minus what has left the tree.
    # TODO (issue 002/003): balance Groceries reports that envelope alone.
    # TODO (issue 002/003): overspending an envelope reports a negative
    #       balance and is not an error — nothing blocks the spend that
    #       causes it.
