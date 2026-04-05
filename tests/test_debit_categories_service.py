from sqlalchemy.orm import Session
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.domain.models import DebitCategory
from kohle.services.debit_categories_services import (
    add_debit_category_service,
    list_debit_categories_service,
)
from kohle.domain.domain_errors import (
    DuplicateCategory
)


def test_add_category_success(session: Session) -> None:
    ctx = DbTransactionContext(session)
    result = add_debit_category_service(ctx, "Groceries")
    assert result.is_ok
    unwrapped_res = result.unwrap()
    assert isinstance(result.unwrap(), DebitCategory)
    assert unwrapped_res.category == "Groceries"


def test_add_category_duplicate(session: Session) -> None:
    ctx = DbTransactionContext(session)
    add_debit_category_service(ctx, "Groceries")
    result = add_debit_category_service(ctx, "Groceries")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateCategory)


def test_list_categories(session: Session) -> None:
    ctx = DbTransactionContext(session)
    add_debit_category_service(ctx, "Food")
    add_debit_category_service(ctx, "Transport")
    result = list_debit_categories_service(ctx)
    assert result.is_ok
    rows = result.unwrap()
    assert [c.category for c in rows] == ["Food", "Transport"]

