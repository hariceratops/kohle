from typing import List
from sqlalchemy.orm import Session
from kohle.core.result import Result
from kohle.domain.models import DebitCategory
from kohle.domain.domain_errors import DuplicateCategory, CategoryError
from kohle.infrastructure.uow import UnitOfWork
from kohle.infrastructure.infra_errors import UniqueViolation, InfrastructureError


def add_debit_category_service(uow: UnitOfWork[int], name: str) -> Result[int, CategoryError]:
    def op(session: Session) -> int:
        category = DebitCategory(category=name)
        session.add(category)
        # triggers DB validation, todo: is such operations allowed in the 
        # in the services and confined to infrastucture
        session.flush()
        return category.id

    result = uow.run(op)

    if result.is_err:
        err = result.unwrap_err()
        if isinstance(err, UniqueViolation) and err.constraint == "uq_debit_category_category":
            return Result.err(DuplicateCategory())
        return Result.err(CategoryError(str(err)))

    return result


def list_debit_categories_service(uow: UnitOfWork[List[DebitCategory]]) -> Result[List[DebitCategory], CategoryError]:
    def op(session: Session) -> List[DebitCategory]:
        return session.query(DebitCategory).order_by(DebitCategory.category).all()

    result = uow.run(op)

    if result.is_err:
        return Result.err(CategoryError(str(result.unwrap_err())))

    return result

