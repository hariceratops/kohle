# tests/test_debit_category_service.py
import pytest
from kohle.services.categories import add_debit_category, CategoryAddResult
from kohle.models import DebitCategory


def test_add_new_category(db_session):
    result = add_debit_category(db_session, "Groceries")
    assert isinstance(result, CategoryAddResult)
    assert result.added is True
    assert result.warnings == ()

    cat = db_session.query(DebitCategory).filter_by(category="Groceries").one()
    assert cat is not None


def test_add_duplicate_category(db_session):
    add_debit_category(db_session, "Rent")
    result = add_debit_category(db_session, "rent")
    assert result.added is False
    assert result.warnings == ()


def test_similar_category_warns(db_session):
    add_debit_category(db_session, "Transport")
    result = add_debit_category(db_session, "Transportation")
    assert result.added is True
    assert "Transport" in result.warnings

