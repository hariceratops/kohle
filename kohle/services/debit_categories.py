from kohle.models.models import DebitCategory
from kohle.core.result import Result
from kohle.services.errors import CategoryError, EmptyCategoryError, DatabaseError
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


def load_debit_categories(uow: UnitOfWork) -> Result[list[dict], DatabaseError]:
    """
    Load all debit categories from the database.
    Returns a Result containing a list of dicts with 'id' and 'category'.
    """
    def op(session):
        categories = session.query(DebitCategory).order_by(DebitCategory.id).all()
        return [{"id": c.id, "category": c.category} for c in categories]

    return uow.run(op)

