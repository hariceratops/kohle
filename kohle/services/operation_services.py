from typing import List
from sqlalchemy.orm import Session
from kohle.domain.models import Operation
from kohle.infrastructure.crud import crud_retrieve
from kohle.infrastructure.uow import DbTransactionContext
from kohle.core.result import Result


@crud_retrieve
def list_operations_service(ctx: DbTransactionContext) -> Result[List[Operation], Exception]:
    def op(session: Session) -> List[Operation]:
        return session.query(Operation).all()
    return (
        ctx.run(op)
        .map_err(lambda err: Exception(str(err)))
    )

