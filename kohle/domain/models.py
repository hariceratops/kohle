from datetime import datetime
from sqlalchemy import Column, Integer, String, UniqueConstraint, ForeignKey, Date, Numeric, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from kohle.db.connection import base
from kohle.infrastructure.model_serde import SerdePolicy, PassAll, PassId


class RegisteredBase(DeclarativeBase):
    __abstract__ = True

    @classmethod
    def __get_policy__(cls) -> SerdePolicy:
        mapper = cls.__mapper__
        relations = {r.key: SerdePolicy(PassId(), {}) for r in mapper.relationships}
        return SerdePolicy(PassAll(), relations)


class Archivable:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OperationGroup(base):
    __tablename__ = "operation_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Operation(base):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("operation_groups.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    field: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str | None] = mapped_column(String, nullable=True)


class DebitCategory(base, Archivable):
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


class Account(base, Archivable):
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


class Transaction(base, Archivable):
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

