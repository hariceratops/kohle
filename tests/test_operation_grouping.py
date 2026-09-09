"""Layer 3 — that the audit trail records a group per write and nothing per read.

Issue 011. The group used to be created in `DbTransactionContext.__init__`, so
every command wrote one, including read-only ones: the table grew with read
traffic and group ids for consecutive writes came out with gaps between them.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from kohle.domain.models import AccountType, Operation, OperationGroup
from kohle.use_cases.accounts import AddAccount, ListAccount
from kohle.use_cases.journal import RecordSimpleEntry
from kohle.use_cases.operations import ListOperations


def _counts(session_factory: sessionmaker) -> tuple[int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(OperationGroup)),
            session.scalar(select(func.count()).select_from(Operation)),
        )


def test_read_only_use_case_creates_no_group(session_factory: sessionmaker) -> None:
    for _ in range(5):
        assert ListAccount(session_factory()).execute().is_ok
    assert ListOperations(session_factory()).execute().is_ok

    assert _counts(session_factory) == (0, 0)


def test_write_creates_exactly_one_group_holding_its_operations(
    session_factory: sessionmaker,
) -> None:
    AddAccount(session_factory()).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session_factory()).execute("Unallocated", AccountType.asset)

    result = RecordSimpleEntry(session_factory()).execute(
        date(2026, 3, 1), "Withdraw cash", Decimal(200), "Checking", "Unallocated"
    )
    assert result.is_ok

    with session_factory() as session:
        groups = session.scalars(select(OperationGroup.id)).all()
        entry_ops = session.scalars(
            select(Operation).where(Operation.group_id == groups[-1])
        ).all()

    # Two accounts, then one entry: three writes, three groups.
    assert len(groups) == 3
    # The entry's group holds every write the entry made — the EUR unit
    # created on demand as well as the entry itself. Lines cascade with the
    # entry and are not separately audited.
    assert {op.entity_type for op in entry_ops} == {"units", "journal_entries"}


def test_reads_between_writes_leave_no_gap_in_group_ids(
    session_factory: sessionmaker,
) -> None:
    AddAccount(session_factory()).execute("Checking", AccountType.asset, "DE1")
    for _ in range(5):
        ListAccount(session_factory()).execute()
    AddAccount(session_factory()).execute("Groceries", AccountType.expense)

    with session_factory() as session:
        group_ids = session.scalars(select(OperationGroup.id).order_by(OperationGroup.id)).all()

    assert group_ids == [group_ids[0], group_ids[0] + 1]


def test_failed_use_case_leaves_no_group_and_no_operations(
    session_factory: sessionmaker,
) -> None:
    assert AddAccount(session_factory()).execute("   ", AccountType.asset).is_err

    assert _counts(session_factory) == (0, 0)
