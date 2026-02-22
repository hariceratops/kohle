from sqlalchemy import insert
from sqlalchemy.orm import Session
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.transactions_services import (
    bulk_insert_transactions_service,
    existing_transactions_service,
)
from kohle.domain.domain_errors import (
    DuplicationTransactionError
)
from kohle.domain.models import Transaction

#
# def test_bulk_insert_transactions_success(session: Session) -> None:
#     uow = UnitOfWork(session)
#     rows = [
#         { "account_id": 1, "hash": "hash1", "description": "A", "date": "2024-01-01", "amount": 10.0 },
#         { "account_id": 1, "hash": "hash2", "description": "B", "date": "2024-01-02", "amount": 20.0 }
#     ]
#     result = bulk_insert_transactions_service(uow, rows)
#     assert result.is_ok
#     assert result.unwrap() == 2
#
#
# def test_bulk_insert_transactions_duplicate(session: Session) -> None:
#     uow = UnitOfWork(session)
#     rows = [
#         { "account_id": 1, "hash": "dup_hash", "description": "A", "date": "2024-01-01", "amount": 10.0 },
#         { "account_id": 1, "hash": "dup_hash", "description": "A", "date": "2024-01-01", "amount": 10.0 }
#     ]
#
#     bulk_insert_transactions_service(uow, rows)
#     result = bulk_insert_transactions_service(uow, rows)
#     assert result.is_err
#     assert isinstance(result.unwrap_err(), DuplicationTransactionError)
#
#
# def test_existing_transactions_service(session: Session) -> None:
#     uow = UnitOfWork(session)
#     rows = [
#         { "account_id": 1, "hash": "hash1", "description": "A", "date": "2024-01-01", "amount": 10.0 },
#         { "account_id": 1, "hash": "hash2", "description": "B", "date": "2024-01-02", "amount": 20.0 }
#     ]
#     session.execute(insert(Transaction), rows)
#     session.commit()
#     result = existing_transactions_service(uow, ["hash1", "hash3"])
#     assert result.is_ok
#     assert result.unwrap() == {"hash1"}
#
#
# def test_existing_transactions_empty(session: Session) -> None:
#     uow = UnitOfWork(session)
#     result = existing_transactions_service(uow, ["nonexistent"])
#     assert result.is_ok
#     assert result.unwrap() == set()
