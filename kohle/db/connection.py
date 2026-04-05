from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base


DATABASE_URL = "sqlite:///kohle.db"


engine = create_engine(DATABASE_URL, future=True)
session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
base = declarative_base()

@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

