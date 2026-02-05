from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


DATABASE_URL = "sqlite:///kohle.db"


engine = create_engine(DATABASE_URL, future=True)
session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
base = declarative_base()

