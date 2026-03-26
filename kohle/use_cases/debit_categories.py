from typing import List
from kohle.core.result import Result
from kohle.infrastructure.uow import UnitOfWork
from kohle.domain.models import DebitCategory
from kohle.domain.domain_errors import CategoryError, EmptyCategoryName
from kohle.services.debit_categories_services import add_debit_category_service, list_debit_categories_service


def add_debit_category(uow: UnitOfWork, name: str) -> Result[DebitCategory, CategoryError]:
    name = name.strip()
    if not name:
        return Result.err(EmptyCategoryName())
    return add_debit_category_service(uow, name)


def list_debit_categories(uow: UnitOfWork) -> Result[List[DebitCategory], CategoryError]:
    return list_debit_categories_service(uow)

