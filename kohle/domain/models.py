from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class DebitCategory(Base):
    __tablename__ = "debit_categories"
    __table_args__ = (
        UniqueConstraint("category", name="uq_debit_category_category"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String, nullable=False, unique=True)

    def __repr__(self) -> str:
        return f"<DebitCategory(id={self.id}, category='{self.category}')>"

