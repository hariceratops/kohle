from typing import Iterable, Set, List
from sqlalchemy.orm import Session
from sqlalchemy import insert
from kohle.domain.models import Transaction, Account
from kohle.infrastructure.crud import crud_retrieve
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.domain.domain_errors import TransactionError, DuplicationTransactionError
from kohle.infrastructure.infra_errors import check_if_unique_constraint_failed
from kohle.core.result import Result


# @crud_bulk_create
def bulk_insert_transactions_service(ctx: DbTransactionContext, rows: list[dict]) -> Result[int, TransactionError]:
    def op(session: Session) -> int:
        _ = session.execute(insert(Transaction), rows)
        return len(rows)

    return (
        ctx.run(op)
        .map(lambda v: v)
        .map_err(lambda err: (
            DuplicationTransactionError() if check_if_unique_constraint_failed(err, "transactions.hash")
            else TransactionError(str(err))
        ))
    )


@crud_retrieve
def existing_transactions_service(ctx: DbTransactionContext, hashes: Iterable[str]) \
        -> Result[Set[str], TransactionError]:
    def op(session: Session) -> Set[str]:
        rows = (
            session.query(Transaction.hash)
            .filter(Transaction.hash.in_(hashes))
            .all()
        )
        return {row[0] for row in rows}

    return (
        ctx.run(op)
        .map_err(lambda err: TransactionError(str(err)))
    )


@crud_retrieve
def query_transactions_by_period_service(ctx: DbTransactionContext,
                                       account_id: int, 
                                       start_date,
                                       end_date) \
                -> Result[List[Transaction], TransactionError]:
    def op(session: Session) -> List[Transaction]:
        transactions = (
            session.query(Transaction)
            .filter(Transaction.date.between(start_date, end_date))
            .filter(Transaction.account_id == account_id)
            .order_by(Transaction.date.asc())
            .all()
        )
        return transactions

    return (
        ctx.run(op)
        .map(lambda v: v)
        .map_err(lambda err: TransactionError(str(err)))
    )


