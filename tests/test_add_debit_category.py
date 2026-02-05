import pytest
from kohle.db.connection import base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from kohle.db.uow import UnitOfWork
from kohle.services.debit_categories import add_debit_category
from kohle.services.errors import EmptyCategoryError, DuplicateCategoryError


# In-memory SQLite
TEST_DB = "sqlite:///:memory:"
engine = create_engine(TEST_DB)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
base.metadata.create_all(bind=engine)


@pytest.fixture
def uow():
    return UnitOfWork(TestingSessionLocal)

def test_add_valid_category(uow):
    result = add_debit_category(uow, "Groceries")
    assert result.is_ok

def test_add_empty_category(uow):
    result = add_debit_category(uow, "")
    assert result.is_err
    assert isinstance(result.unwrap_err(), EmptyCategoryError)

def test_add_duplicate_category(uow):
    add_debit_category(uow, "Transport")
    result = add_debit_category(uow, "Transport")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateCategoryError)

