from typing import Iterable, Set
from sqlalchemy.orm import Session
from sqlalchemy import insert
from kohle.domain.models import Transaction
from kohle.infrastructure.uow import UnitOfWork
from kohle.domain.domain_errors import TransactionError, DuplicationTransactionError
from kohle.infrastructure.infra_errors import check_if_unique_constraint_failed
from kohle.core.result import Result


def bulk_insert_transactions_service(uow: UnitOfWork[int], rows: list[dict]) -> Result[int, TransactionError]:
    def op(session: Session) -> int:
        _ = session.execute(insert(Transaction), rows)
        session.flush()  # triggers DB validation
        return len(rows)

    return (
        uow.run(op)
        .map(lambda v: v)
        .map_err(lambda err: (
            DuplicationTransactionError() if check_if_unique_constraint_failed(err, "transaction.hash")
            else TransactionError(str(err))
        ))
    )


def existing_transactions_service(uow: UnitOfWork[Set[str]], hashes: Iterable[str]) -> Result[Set[str], TransactionError]:
    def op(session: Session) -> Set[str]:
        rows = (
            session.query(Transaction.hash)
            .filter(Transaction.hash.in_(hashes))
            .all()
        )
        return {row[0] for row in rows}

    return (
        uow.run(op)
        .map_err(lambda err: TransactionError(str(err)))
    )

