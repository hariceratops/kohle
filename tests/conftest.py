# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from kohle.models import base

# Use an in-memory SQLite database for tests
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_session():
    # Create an engine
    engine = create_engine(TEST_DATABASE_URL, echo=False)

    # Create all tables
    base.metadata.create_all(bind=engine)

    # Create a session factory
    TestingSessionLocal = sessionmaker(bind=engine)

    # Provide a session to the test
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        # Cleanup: close session and drop tables
        session.close()
        base.metadata.drop_all(bind=engine)

