from sqlalchemy import Column, Integer, String, UniqueConstraint, ForeignKey, Date, Numeric
from kohle.db.connection import base
from sqlalchemy.orm import Mapped, mapped_column


class DebitCategory(base):
    __tablename__ = "debit_categories"
    __table_args__ = (
        UniqueConstraint("category", name="uq_debit_category_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category = Column(String, nullable=False, unique=True)

    def __repr__(self) -> str:
        return f"<DebitCategory(id={self.id}, category='{self.category}')>"

class Account(base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    iban = Column(String, nullable=False, unique=True)

    __table_args__ = (
        UniqueConstraint("name", name="uq_account_name"),
        UniqueConstraint("iban", name="uq_account_iban"),
    )


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

