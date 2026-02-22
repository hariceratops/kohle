from typing import List
from sqlalchemy.orm import Session
from kohle.core.result import Result
from kohle.domain.models import DebitCategory
from kohle.domain.domain_errors import DuplicateCategory, CategoryError
from kohle.infrastructure.uow import UnitOfWork
from kohle.infrastructure.infra_errors import check_if_unique_constraint_failed


def add_debit_category_service(uow: UnitOfWork[int], name: str) -> Result[int, CategoryError]:
    def op(session: Session) -> int:
        category = DebitCategory(category=name)
        session.add(category)
        session.flush()  # triggers DB validation
        return category.id

    return (
        uow.run(op)
        .map_err(lambda err: (
            DuplicateCategory(name)
            if check_if_unique_constraint_failed(err, "debit_categories.category")
            else CategoryError(str(err))
        ))
    )


def list_debit_categories_service(uow: UnitOfWork[List[DebitCategory]]) -> Result[List[DebitCategory], CategoryError]:
    def op(session: Session) -> List[DebitCategory]:
        return session.query(DebitCategory).order_by(DebitCategory.category).all()
    return (
        uow.run(op)
        .map_err(lambda err: CategoryError(str(err)))
    )
    
