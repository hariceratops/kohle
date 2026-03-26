from sqlalchemy.orm import Session
from kohle.infrastructure.uow import UnitOfWork
from kohle.domain.models import DebitCategory
from kohle.use_cases.debit_categories import (
    add_debit_category,
    list_debit_categories,
)
from kohle.domain.domain_errors import (
    EmptyCategoryName,
    DuplicateCategory,
)


def test_add_debit_category_success(session: Session) -> None:
    uow = UnitOfWork(session)
    result = add_debit_category(uow, "Groceries")
    assert result.is_ok
    unwrapped_res = result.unwrap()
    assert isinstance(result.unwrap(), DebitCategory)
    assert unwrapped_res.category == "Groceries"


def test_add_debit_category_empty_name(session: Session) -> None:
    uow = UnitOfWork(session)
    result = add_debit_category(uow, "   ")
    assert result.is_err
    assert isinstance(result.unwrap_err(), EmptyCategoryName)


def test_add_debit_category_duplicate(session: Session) -> None:
    uow = UnitOfWork(session)
    add_debit_category(uow, "Food")
    result = add_debit_category(uow, "Food")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateCategory)


def test_list_debit_categories(session: Session) -> None:
    uow = UnitOfWork(session)
    add_debit_category(uow, "Food")
    add_debit_category(uow, "Transport")
    result = list_debit_categories(uow)
    assert result.is_ok
    rows = result.unwrap()
    assert rows == [
        DebitCategory(id=1, category="Food"),
        DebitCategory(id=2, category="Transport")
    ]
