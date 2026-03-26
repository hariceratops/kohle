from datetime import datetime
from typing import Dict, Type, TypeVar, Callable
from sqlalchemy import Column, Integer, String, UniqueConstraint, ForeignKey, Date, Numeric, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from kohle.db.connection import base
from kohle.infrastructure.model_serde import SerdePolicy


class DebitCategory(base):
    __tablename__ = "debit_categories"
    __table_args__ = (
        UniqueConstraint("category", name="uq_debit_category_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category = Column(String, nullable=False, unique=True)

    def __eq__(self, other) -> bool:
        return self.id == other.id and self.category == other.category

    def __repr__(self) -> str:
        return f"<DebitCategory(id={self.id}, category='{self.category}')>"


class Account(base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    iban = Column(String, nullable=False, unique=True)

    transactions = relationship("Transaction", back_populates="account")

    __table_args__ = (
        UniqueConstraint("name", name="uq_account_name"),
        UniqueConstraint("iban", name="uq_account_iban"),
    )

    def __eq__(self, other) -> bool:
        return self.id == other.id and \
               self.name == other.name and \
               self.iban == other.iban

    def __repr__(self) -> str:
        return f"<Account(id={self.id}, name={self.name}, iban={self.iban})>"


class Transaction(base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("hash", name="uq_transaction_hash"),
    )
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"))
    hash = Column(String(64), nullable=False, unique=True)
    description = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)

    account = relationship("Account")

    def __eq__(self, other) -> bool:
        return self.id == other.id and \
               self.account_id == other.account_id and \
               self.description == other.description and \
               self.date == other.date and \
               self.amount == other.amount and \
               self.hash == other.hash

