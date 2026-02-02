from sqlalchemy import Column, Integer, String
from db import base

class DebitCategory(base):
    __tablename__ = "debit_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String, unique=True, nullable=False)

    def __repr__(self):
        return f"<DebitCategory(id={self.id}, category='{self.category}')>"
