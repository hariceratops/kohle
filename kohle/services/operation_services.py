from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.models import Operation
from kohle.infrastructure.crud import crud_retrieve
from kohle.infrastructure.uow import DbTransactionContext


@crud_retrieve
def list_operations_service(ctx: DbTransactionContext) -> Result[list[Operation], Exception]:
    def op(session: Session) -> list[Operation]:
        # group_id DESC, id ASC: most recent transaction first, with the
        # steps inside one transaction in the order they happened. Groups
        # commit in id order and id is autoincrement, so group_id is a
        # reliable recency key without joining operation_groups.
        return session.query(Operation).order_by(Operation.group_id.desc(), Operation.id.asc()).all()
    return (
        ctx.run(op)
        .map_err(lambda err: Exception(str(err)))
    )

