from sqlalchemy import insert
from datetime import date
from sqlalchemy.orm import Session
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.transactions_services import (
    bulk_insert_transactions_service,
    existing_transactions_service,
    query_transactions_by_period_service
)
from kohle.domain.domain_errors import (
    DuplicationTransactionError
)
from kohle.domain.models import Account, Transaction


def _create_account(session: Session):
    account = Account(name="Alice", iban="DE123")
    session.add(account)
    session.flush()
    return account


def _create_transaction(session: Session, account_id: int, tx_date: date, description: str, amount: float):
    tx = Transaction(
        account_id=account_id,
        date=tx_date,
        description=description,
        amount=amount,
        hash=f"{tx_date}|{amount}|{description}",
    )
    session.add(tx)
    return tx


def test_bulk_insert_transactions_success(session: Session) -> None:
    ctx = DbTransactionContext(session)
    rows = [
        { "account_id": 1, "hash": "hash1", "description": "A", "date": date(2024, 1, 1), "amount": 10.0 },
        { "account_id": 1, "hash": "hash2", "description": "B", "date": date(2024, 1, 2), "amount": 20.0 }
    ]
    result = bulk_insert_transactions_service(ctx, rows)
    assert result.is_ok
    assert result.unwrap() == 2


def test_bulk_insert_transactions_duplicate(session: Session) -> None:
    ctx = DbTransactionContext(session)
    rows = [
        { "account_id": 1, "hash": "dup_hash", "description": "A", "date": date(2024, 1, 1), "amount": 10.0 },
        { "account_id": 1, "hash": "dup_hash", "description": "A", "date": date(2024, 1, 1), "amount": 10.0 }
    ]

    bulk_insert_transactions_service(ctx, rows)
    result = bulk_insert_transactions_service(ctx, rows)
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicationTransactionError)


def test_existing_transactions_service(session: Session) -> None:
    ctx = DbTransactionContext(session)
    rows = [
        { "account_id": 1, "hash": "hash1", "description": "A", "date": date(2024, 1, 1), "amount": 10.0 },
        { "account_id": 1, "hash": "hash2", "description": "B", "date": date(2024, 1, 2), "amount": 20.0 }
    ]
    session.execute(insert(Transaction), rows)
    session.commit()
    result = existing_transactions_service(ctx, ["hash1", "hash3"])
    assert result.is_ok
    assert result.unwrap() == {"hash1"}


def test_existing_transactions_empty(session: Session) -> None:
    ctx = DbTransactionContext(session)
    result = existing_transactions_service(ctx, ["nonexistent"])
    assert result.is_ok
    assert result.unwrap() == set()


def test_query_transactions_by_period_returns_results(session: Session):
    account = _create_account(session)
    _create_transaction(session, account.id, date(2024, 1, 1), "A", 10.0)
    _create_transaction(session, account.id, date(2024, 1, 2), "B", 20.0)
    _create_transaction(session, account.id, date(2024, 1, 3), "C", 30.0)
    session.commit()

    ctx = DbTransactionContext(session)
    result = query_transactions_by_period_service(
        ctx,
        account.id,
        date(2024, 1, 1),
        date(2024, 1, 3),
    )

    assert result.is_ok
    data = result.unwrap()
    assert len(data) == 3
    assert [t.description for t in data] == ["A", "B", "C"]


def test_query_transactions_excludes_outside_range(session: Session):
    account = _create_account(session)
    _create_transaction(session, account.id, date(2024, 1, 5), "Inside", 10.0)
    _create_transaction(session, account.id, date(2024, 2, 1), "Outside", 20.0)
    session.commit()

    ctx = DbTransactionContext(session)
    result = query_transactions_by_period_service(
        ctx,
        account.id,
        date(2024, 1, 1),
        date(2024, 1, 31),
    )

    assert result.is_ok
    data = result.unwrap()
    assert len(data) == 1
    assert data[0].description == "Inside"


def test_query_transactions_sorted_by_date(session: Session):
    account = _create_account(session)
    _create_transaction(session, account.id, date(2024, 1, 3), "C", 10.0)
    _create_transaction(session, account.id, date(2024, 1, 1), "A", 20.0)
    _create_transaction(session, account.id, date(2024, 1, 2), "B", 30.0)
    session.commit()

    ctx = DbTransactionContext(session)
    result = query_transactions_by_period_service(
        ctx,
        account.id,
        date(2024, 1, 1),
        date(2024, 1, 31),
    )

    assert result.is_ok
    data = result.unwrap()
    assert [t.description for t in data] == ["A", "B", "C"]


def test_query_transactions_empty_result(session: Session):
    account = _create_account(session)
    session.commit()

    ctx = DbTransactionContext(session)
    result = query_transactions_by_period_service(
        ctx,
        account.id,
        date(2024, 1, 1),
        date(2024, 1, 31),
    )

    assert result.is_ok
    assert result.unwrap() == []
