from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from kohle.domain.domain_errors import DuplicateJournalEntry
from kohle.domain.models import AccountType, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import add_account_service
from kohle.services.journal_services import (
    LineSpec,
    add_journal_entry_service,
    existing_references_service,
    query_lines_by_period_service,
)
from kohle.services.unit_services import add_unit_service


def _fixture(ctx: DbTransactionContext) -> tuple[int, int, int]:
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
    groceries = add_account_service(ctx, "Groceries", AccountType.expense).unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    return checking.id, groceries.id, eur.id


def _cash_lines(checking_id: int, groceries_id: int, eur_id: int, amount: str) -> list[LineSpec]:
    value = Decimal(amount)
    return [
        LineSpec(groceries_id, eur_id, value, Decimal(1), is_debit=True),
        LineSpec(checking_id, eur_id, value, Decimal(1), is_debit=False),
    ]


def test_add_entry_persists_lines(session: Session) -> None:
    ctx = DbTransactionContext(session)
    checking_id, groceries_id, eur_id = _fixture(ctx)

    result = add_journal_entry_service(
        ctx, date(2026, 3, 1), "ref-1", "Aldi",
        _cash_lines(checking_id, groceries_id, eur_id, "80"),
    )
    assert result.is_ok
    entry = result.unwrap()
    assert len(entry.lines) == 2
    assert {line.is_debit for line in entry.lines} == {True, False}
    assert all(line.unit_price == Decimal(1) for line in entry.lines)


def test_duplicate_reference_rejected(session: Session) -> None:
    ctx = DbTransactionContext(session)
    checking_id, groceries_id, eur_id = _fixture(ctx)

    add_journal_entry_service(
        ctx, date(2026, 3, 1), "ref-1", "Aldi",
        _cash_lines(checking_id, groceries_id, eur_id, "80"),
    )
    result = add_journal_entry_service(
        ctx, date(2026, 3, 2), "ref-1", "Aldi again",
        _cash_lines(checking_id, groceries_id, eur_id, "90"),
    )
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateJournalEntry)


def test_existing_references(session: Session) -> None:
    ctx = DbTransactionContext(session)
    checking_id, groceries_id, eur_id = _fixture(ctx)
    add_journal_entry_service(
        ctx, date(2026, 3, 1), "ref-1", "Aldi",
        _cash_lines(checking_id, groceries_id, eur_id, "80"),
    )

    result = existing_references_service(ctx, ["ref-1", "ref-2"])
    assert result.is_ok
    assert result.unwrap() == {"ref-1"}


def test_query_lines_by_period(session: Session) -> None:
    ctx = DbTransactionContext(session)
    checking_id, groceries_id, eur_id = _fixture(ctx)
    for day, ref in ((1, "a"), (15, "b"), (28, "c")):
        add_journal_entry_service(
            ctx, date(2026, 3, day), ref, "shopping",
            _cash_lines(checking_id, groceries_id, eur_id, "10"),
        )

    result = query_lines_by_period_service(ctx, checking_id, date(2026, 3, 10), date(2026, 3, 20))
    assert result.is_ok
    lines = result.unwrap()
    assert len(lines) == 1
    assert lines[0].entry.reference == "b"


def test_line_value_is_quantity_times_price(session: Session) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
    broker = add_account_service(ctx, "Broker", AccountType.asset, "DE2").unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    share = add_unit_service(ctx, "IE00B4L5Y983", "Core MSCI World", UnitKind.security).unwrap()

    result = add_journal_entry_service(
        ctx, date(2026, 3, 1), "buy-1", "Bought 10 shares",
        [
            LineSpec(broker.id, share.id, Decimal(10), Decimal(100), is_debit=True),
            LineSpec(checking.id, eur.id, Decimal(1000), Decimal(1), is_debit=False),
        ],
    )
    assert result.is_ok
    debit, credit = sorted(result.unwrap().lines, key=lambda line: not line.is_debit)
    assert debit.value == credit.value == Decimal(1000)
    assert debit.quantity == Decimal(10)
