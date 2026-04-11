from typing import List
from kohle.core.result import Result
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.domain.models import Operation
from kohle.services.operation_services import list_operations_service


class ListOperations(UnitOfWork[List[Operation], Exception]):
    def execute(self) -> Result[List[Operation], Exception]:
        def use_case(ctx: DbTransactionContext) -> Result[List[Operation], Exception]:
            return list_operations_service(ctx)
        return self._run(use_case)

