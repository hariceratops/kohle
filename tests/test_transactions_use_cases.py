import pandas as pd
from datetime import date
from sqlalchemy.orm import Session

from kohle.services.account_services import (add_account_service)
from kohle.use_cases.transactions import import_transaction_statement
from kohle.domain.domain_errors import (
    AccountNotFoundError,
    TransactionError,
)
from kohle.domain.models import Account, Transaction


def test_import_success_new_transactions(session: Session) -> None:
    account = Account(name="Alice", iban="DE123")
    session.add(account)
    session.flush()
    session.commit()
    df = pd.DataFrame([
        { "date": date(2024, 1, 1), "amount": 10.0, "description": "A" },
        { "date": date(2024, 1, 2), "amount": 20.0, "description": "B" },
    ])
    result = import_transaction_statement("Alice", df)
    assert result.is_ok
    assert result.unwrap() == 2


# def test_import_account_not_found(session: Session) -> None:
#     df = pd.DataFrame(
#         [
#             {
#                 "date": date(2024, 1, 1),
#                 "amount": 10.0,
#                 "description": "A",
#             }
#         ]
#     )
#
#     result = import_transaction_statement("Missing", df)
#
#     assert result.is_err
#     assert isinstance(result.unwrap_err(), AccountNotFoundError)
#
#
# def test_import_no_new_transactions(session: Session) -> None:
#     uow = UnitOfWork(session)
#
#     account = Account(name="Alice", iban="DE123")
#     session.add(account)
#     session.commit()
#
#     df = pd.DataFrame(
#         [
#             {
#                 "date": date(2024, 1, 1),
#                 "amount": 10.0,
#                 "description": "A",
#             }
#         ]
#     )
#
#     result1 = import_transaction_statement("Alice", df)
#     assert result1.is_ok
#     assert result1.unwrap() == 1
#
#     result2 = import_transaction_statement("Alice", df)
#     assert result2.is_ok
#     assert result2.unwrap() == 0
#
#
# def test_import_bulk_insert_error(session: Session) -> None:
#     uow = UnitOfWork(session)
#
#     account = Account(name="Alice", iban="DE123")
#     session.add(account)
#     session.commit()
#
#     df = pd.DataFrame(
#         [
#             {
#                 "date": date(2024, 1, 1),
#                 "amount": 10.0,
#                 "description": "A",
#             }
#         ]
#     )
#
#     result = import_transaction_statement("Alice", df)
#
#     assert result.is_ok
