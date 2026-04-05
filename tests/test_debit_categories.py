from sqlalchemy.orm import Session
from kohle.domain.models import DebitCategory
from kohle.domain.domain_errors import (
    EmptyCategoryName,
    DuplicateCategory,
)
from kohle.use_cases.debit_categories import (
    AddDebitCategory,
    ListCategories,
)


def test_add_debit_category_success(session: Session) -> None:
    add_debit_category = AddDebitCategory(session)
    result = add_debit_category.execute("Groceries")
    assert result.is_ok
    unwrapped_res = result.unwrap()
    assert isinstance(result.unwrap(), DebitCategory)
    assert unwrapped_res.category == "Groceries"


def test_add_debit_category_empty_name(session: Session) -> None:
    add_debit_category = AddDebitCategory(session)
    result = add_debit_category.execute("Groceries")
    result = add_debit_category.execute("   ")
    assert result.is_err
    assert isinstance(result.unwrap_err(), EmptyCategoryName)


def test_add_debit_category_duplicate(session: Session) -> None:
    add_debit_category = AddDebitCategory(session)
    result = add_debit_category.execute("Groceries")
    result = add_debit_category.execute("Food")
    result = add_debit_category.execute("Food")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateCategory)


def test_list_debit_categories(session: Session) -> None:
    add_debit_category = AddDebitCategory(session)
    add_debit_category.execute("Food")
    add_debit_category.execute("Transport")
    add_debit_category.execute("Groceries")
    list_debit_categories = ListCategories(session)
    result = list_debit_categories.execute()
    assert result.is_ok
    rows = result.unwrap()
    rows = sorted(rows, key=lambda r: r.id)
    assert rows == [
        DebitCategory(id=1, category="Food"),
        DebitCategory(id=2, category="Transport"),
        DebitCategory(id=3, category="Groceries")
    ]
