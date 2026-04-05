import pandas as pd
from datetime import date
from sqlalchemy.orm import Session
from kohle.use_cases.transactions import ImportTransactionStatement, QueryTransactionByPeriod
from kohle.domain.domain_errors import (
    AccountNotFoundError,
    DataframeValidationError,
    QueryTransactionByPeriodError,
    EndDatePrecedesStartDateError,
    InvalidDateError
)
from kohle.domain.models import Account, Transaction


def test_import_missing_column(session: Session) -> None:
    account = Account(name="Alice", iban="DE123")
    session.add(account)
    session.commit()

    df = pd.DataFrame([
        { "date": pd.Timestamp(2024, 1, 1), "description": "A", "iban": "DE123" }
    ])  # amount column missing
    
    import_transaction_statement = ImportTransactionStatement(session)
    result = import_transaction_statement.execute("Alice", df)
    assert result.is_err
    assert isinstance(result.unwrap_err(), DataframeValidationError)


def test_import_type_mismatch(session: Session) -> None:
    account = Account(name="Alice", iban="DE123")
    session.add(account)
    session.commit()

    df = pd.DataFrame([
        { 
            "date": pd.Timestamp(2024, 1, 1),
            "amount": "not_a_float",  # type mismatch
            "description": "A",
            "iban": "DE123"
        }
    ])
    import_transaction_statement = ImportTransactionStatement(session)
    result = import_transaction_statement.execute("Alice", df)
    assert result.is_err
    assert isinstance(result.unwrap_err(), DataframeValidationError)


def test_import_success_new_transactions(session: Session) -> None:
    account = Account(name="Alice", iban="DE123")
    session.add(account)
    session.flush()
    session.commit()
    df = pd.DataFrame([
        { "date": pd.Timestamp(2024, 1, 1), "amount": 10.0, "description": "A", "iban": "DE123" },
        { "date": pd.Timestamp(2024, 1, 2), "amount": 20.0, "description": "B", "iban": "DE123" },
    ])
    import_transaction_statement = ImportTransactionStatement(session)
    result = import_transaction_statement.execute("Alice", df)
    assert result.is_ok
    assert result.unwrap() == 2


def test_import_account_not_found(session: Session) -> None:
    df = pd.DataFrame([
        { "date": pd.Timestamp(2024, 1, 1), "amount": 10.0, "description": "A", "iban": "DE123" }
    ])
    import_transaction_statement = ImportTransactionStatement(session)
    result = import_transaction_statement.execute("Missing", df)
    assert result.is_err
    assert isinstance(result.unwrap_err(), AccountNotFoundError)


def test_import_no_new_transactions(session: Session) -> None:
    account = Account(name="Alice", iban="DE123")
    session.add(account)
    session.commit()

    df = pd.DataFrame([
        { "date": pd.Timestamp(2024, 1, 1), "amount": 10.0, "description": "A", "iban": "DE123" }
    ])

    import_transaction_statement = ImportTransactionStatement(session)
    result1 = import_transaction_statement.execute("Alice", df)
    assert result1.is_ok
    assert result1.unwrap() == 1
    result2 = import_transaction_statement.execute("Alice", df)
    assert result2.is_ok
    assert result2.unwrap() == 0


def test_import_bulk_insert_overlapping(session: Session) -> None:
    account = Account(name="Alice", iban="DE123")
    session.add(account)
    session.commit()

    df = pd.DataFrame([
        { "date": pd.Timestamp(2024, 1, 1), "amount": 10.0, "description": "A", "iban": "DE123" }
    ])
    import_transaction_statement = ImportTransactionStatement(session)
    result = import_transaction_statement.execute("Alice", df)
    df = pd.DataFrame([
        { "date": pd.Timestamp(2024, 1, 1), "amount": 10.0, "description": "A", "iban": "DE123" },
        { "date": pd.Timestamp(2024, 1, 1), "amount": 20.0, "description": "B", "iban": "DE123" }
    ])
    result_overlapping = import_transaction_statement.execute("Alice", df)

    assert result.is_ok
    assert result.unwrap() == 1
    assert result_overlapping.is_ok
    assert result_overlapping.unwrap() == 1

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


def test_query_transaction_by_period_success(session: Session):
    account = _create_account(session)
    _create_transaction(session, account.id, date(2024, 1, 1), "A", 10.0)
    _create_transaction(session, account.id, date(2024, 1, 2), "B", 20.0)
    _create_transaction(session, account.id, date(2024, 1, 3), "C", 30.0)
    session.commit()

    query_transaction_by_period = QueryTransactionByPeriod(session)
    result = query_transaction_by_period.execute(
        "Alice",
        "2024-01-01",
        "2024-01-04",
    )

    assert result.is_ok
    data = result.unwrap()
    assert len(data) == 3
    assert [t["description"] for t in data] == ["A", "B", "C"]


def test_query_transaction_by_period_account_not_found(session: Session):
    query_transaction_by_period = QueryTransactionByPeriod(session)
    result = query_transaction_by_period.execute(
        "Missing",
        "2024-01-01",
        "2024-01-04",
    )

    assert result.is_err
    assert isinstance(result.unwrap_err(), QueryTransactionByPeriodError)


def test_query_transaction_by_period_invalid_start_date(session: Session):
    _ = _create_account(session)
    session.commit()

    query_transaction_by_period = QueryTransactionByPeriod(session)
    result = query_transaction_by_period.execute(
        "Alice",
        "invalid",
        "2024-01-04",
    )

    assert result.is_err
    assert isinstance(result.unwrap_err(), QueryTransactionByPeriodError)


def test_query_transaction_by_period_invalid_end_date(session: Session):
    _ = _create_account(session)
    session.commit()

    query_transaction_by_period = QueryTransactionByPeriod(session)
    result = query_transaction_by_period.execute(
        "Alice",
        "2024-01-01",
        "invalid",
    )

    assert result.is_err
    assert isinstance(result.unwrap_err(), QueryTransactionByPeriodError)


def test_query_transaction_by_period_end_before_start(session: Session):
    _ = _create_account(session)
    session.commit()

    query_transaction_by_period = QueryTransactionByPeriod(session)
    result = query_transaction_by_period.execute(
        "Alice",
        "2024-01-05",
        "2024-01-01",
    )

    assert result.is_err
    assert isinstance(result.unwrap_err(), EndDatePrecedesStartDateError)
