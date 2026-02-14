from typing import List
from kohle.core.result import Result
from kohle.db.connection import session_local
from kohle.infrastructure.uow import UnitOfWork
from kohle.domain.domain_errors import CategoryError, EmptyCategoryName
from kohle.services.debit_categories_services import add_debit_category_service, list_debit_categories_service


def add_debit_category(name: str) -> Result[int, CategoryError]:
    name = name.strip()
    if not name:
        return Result.err(EmptyCategoryName())
    with UnitOfWork(session_local()) as uow:
        return add_debit_category_service(uow, name)


def list_debit_categories() -> Result[List[dict], CategoryError]:
    with UnitOfWork(session_local()) as uow:
        res = list_debit_categories_service(uow)
        if res.is_err:
            return Result.err(res.unwrap_err())
        categories = [{"id": c.id, "category": c.category} for c in res.unwrap()]
        return Result.ok(categories)

