from kohle.core.result import Result
from kohle.domain.models import Operation
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.operation_services import list_operations_service


class ListOperations(UnitOfWork[list[Operation], Exception]):
    def execute(self) -> Result[list[Operation], Exception]:
        def use_case(ctx: DbTransactionContext) -> Result[list[Operation], Exception]:
            return list_operations_service(ctx)
        return self._run(use_case)

