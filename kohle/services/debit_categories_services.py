from typing import List
from sqlalchemy.orm import Session
from kohle.core.result import Result
from kohle.domain.models import DebitCategory
from kohle.domain.domain_errors import DuplicateCategory, CategoryError
from kohle.infrastructure.crud import crud_create, crud_retrieve
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.infra_errors import check_if_unique_constraint_failed


@crud_create
def add_debit_category_service(ctx: DbTransactionContext, name: str) -> Result[DebitCategory, CategoryError]:
    def op(session: Session) -> DebitCategory:
        category = DebitCategory(category=name)
        session.add(category)
        return category

    return (
        ctx.run(op).map(lambda category: category)
        .map_err(lambda err: (
            DuplicateCategory(name)
            if check_if_unique_constraint_failed(err, "debit_categories.category")
            else CategoryError(str(err))
        ))
    )


@crud_retrieve
def list_debit_categories_service(ctx: DbTransactionContext) -> Result[List[DebitCategory], CategoryError]:
    def op(session: Session) -> List[DebitCategory]:
        return session.query(DebitCategory).order_by(DebitCategory.category).all()
    return (
        ctx.run(op)
        .map_err(lambda err: CategoryError(str(err)))
    )
    
