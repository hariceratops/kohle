import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from kohle.db.connection import base


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    sess: Session = SessionLocal()
    try:
        yield sess
    finally:
        sess.close()
        base.metadata.drop_all(bind=engine)
