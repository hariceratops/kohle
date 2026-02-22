from sqlalchemy.orm import Session
from kohle.services.debit_categories_services import (
    add_debit_category_service,
    list_debit_categories_service,
)
from kohle.infrastructure.uow import UnitOfWork
from kohle.domain.domain_errors import (
    EmptyCategoryName,
    DuplicateCategory,
)


def test_add_category_success(session: Session) -> None:
    uow = UnitOfWork(session)
    result = add_debit_category_service(uow, "Groceries")
    assert result.is_ok
    cat_id = result.unwrap()
    assert isinstance(cat_id, int)


def test_add_category_empty(session: Session) -> None:
    uow = UnitOfWork(session)
    result = add_debit_category_service(uow, "")
    assert result.is_err
    assert isinstance(result.unwrap_err(), EmptyCategoryName)


def test_add_category_duplicate(session: Session) -> None:
    uow = UnitOfWork(session)
    add_debit_category_service(uow, "Groceries")
    result = add_debit_category_service(uow, "Groceries")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateCategory)


def test_list_categories(session: Session) -> None:
    uow = UnitOfWork(session)
    add_debit_category_service(uow, "Food")
    add_debit_category_service(uow, "Transport")
    result = list_debit_categories_service(uow)
    assert result.is_ok
    rows = result.unwrap()
    assert [c.category for c in rows] == ["Food", "Transport"]

