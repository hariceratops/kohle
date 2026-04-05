from typing import Callable, List
from kohle.core.result import Result
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import unit_of_work, UnitOfWork
from kohle.domain.models import DebitCategory
from kohle.domain.domain_errors import CategoryError, EmptyCategoryName
from kohle.services.debit_categories_services import add_debit_category_service, list_debit_categories_service


class AddDebitCategory(UnitOfWork[DebitCategory, CategoryError]):
    def execute(self, category_name: str) -> Result[DebitCategory, CategoryError]:
        def use_case(ctx: DbTransactionContext) -> Result[DebitCategory, CategoryError]:
            name = category_name.strip()
            if not name:
                return Result.err(EmptyCategoryName())
            return add_debit_category_service(ctx, name)
        return self._run(use_case)


class ListCategories(UnitOfWork[List[DebitCategory], CategoryError]):
    def execute(self) -> Result[List[DebitCategory], CategoryError]:
        def use_case(ctx: DbTransactionContext) -> Result[List[DebitCategory], CategoryError]:
            return list_debit_categories_service(ctx)
        return self._run(use_case)

