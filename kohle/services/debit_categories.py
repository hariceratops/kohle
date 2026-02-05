from kohle.models.models import DebitCategory
from kohle.core.result import Result
from kohle.services.errors import CategoryError, EmptyCategoryError
from kohle.db.uow import UnitOfWork


def add_debit_category(uow: UnitOfWork, name: str) -> Result[int, CategoryError]:
    name = name.strip()
    if not name:
        return Result.err(EmptyCategoryError())

    def op(session):
        category = DebitCategory(category=name)
        session.add(category)
        return category.id

    return uow.run(op)

