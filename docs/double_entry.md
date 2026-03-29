You asked:
Lets add expense along with undo operation but we can also reuse import transaction from before.
We can assume for now we have only one expense account, without hierarchy. And we want all comit flush operations limited to uow.

Reply:
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Generic, Optional, TypeVar, List

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String, create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, Mapper, Session, mapped_column, relationship, sessionmaker


T = TypeVar("T")


class Result(Generic[T]):
    def __init__(self, value: Optional[T] = None, error: Optional[str] = None) -> None:
        self.value: Optional[T] = value
        self.error: Optional[str] = error

    @property
    def is_ok(self) -> bool:
        return self.error is None

    @staticmethod
    def ok(value: T) -> Result[T]:
        return Result(value=value)

    @staticmethod
    def fail(error: str) -> Result[T]:
        return Result(error=error)


class Base(DeclarativeBase):
    pass


class SinglePrimaryKeyMixin:
    @classmethod
    def __declare_last__(cls) -> None:
        mapper: Mapper = inspect(cls)
        pk_columns = mapper.primary_key
        if len(pk_columns) != 1:
            raise ValueError(f"{cls.__name__} must have exactly one primary key column")


class Operation(Base, SinglePrimaryKeyMixin):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    type: Mapped[str] = mapped_column(String, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class Archivable:
    created_in_operation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("operations.id"),
        nullable=False,
    )

    reverted_in_operation_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("operations.id"),
        nullable=True,
    )


class AccountType(Enum):
    asset = "asset"
    liability = "liability"
    equity = "equity"
    income = "income"
    expense = "expense"


class Account(Base, SinglePrimaryKeyMixin, Archivable):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    name: Mapped[str] = mapped_column(
        String,
        nullable=False,
        unique=True,
    )

    type: Mapped[AccountType] = mapped_column(
        SAEnum(AccountType),
        nullable=False,
    )


class Transaction(Base, SinglePrimaryKeyMixin, Archivable):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    description: Mapped[str] = mapped_column(String, nullable=False)

    date: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )


class Entry(Base, SinglePrimaryKeyMixin, Archivable):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    transaction_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("transactions.id"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id"),
        nullable=False,
    )

    amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )


class UnitOfWork:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory: Callable[[], Session] = session_factory
        self.session: Optional[Session] = None

    def __enter__(self) -> UnitOfWork:
        self.session = self._session_factory()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.session.commit()
        else:
            self.session.rollback()
        self.session.close()

    def flush(self) -> None:
        self.session.flush()


@dataclass
class ImportTransactionCommand:
    description: str
    date: datetime


@dataclass
class AddExpenseCommand:
    description: str
    amount: int
    date: datetime


@dataclass
class UndoOperationCommand:
    operation_id: int


def import_transaction(
    uow: UnitOfWork,
    cmd: ImportTransactionCommand,
) -> Result[Transaction]:
    operation = Operation(type="import_transaction")
    uow.session.add(operation)
    uow.flush()

    transaction = Transaction(
        description=cmd.description,
        date=cmd.date,
        created_in_operation_id=operation.id,
        reverted_in_operation_id=None,
    )

    uow.session.add(transaction)
    uow.flush()

    return Result.ok(transaction)


def add_expense(
    uow_factory: Callable[[], UnitOfWork],
    cmd: AddExpenseCommand,
) -> Result[Transaction]:
    with uow_factory() as uow:
        session: Session = uow.session

        cash: Optional[Account] = (
            session.query(Account)
            .filter(
                Account.type == AccountType.asset,
                Account.reverted_in_operation_id.is_(None),
            )
            .one_or_none()
        )

        expense: Optional[Account] = (
            session.query(Account)
            .filter(
                Account.type == AccountType.expense,
                Account.reverted_in_operation_id.is_(None),
            )
            .one_or_none()
        )

        if cash is None or expense is None:
            return Result.fail("required accounts not found")

        tx_result: Result[Transaction] = import_transaction(
            uow,
            ImportTransactionCommand(
                description=cmd.description,
                date=cmd.date,
            ),
        )

        if not tx_result.is_ok:
            return tx_result

        transaction: Transaction = tx_result.value

        debit_entry = Entry(
            transaction_id=transaction.id,
            account_id=expense.id,
            amount=cmd.amount,
            created_in_operation_id=transaction.created_in_operation_id,
            reverted_in_operation_id=None,
        )

        credit_entry = Entry(
            transaction_id=transaction.id,
            account_id=cash.id,
            amount=-cmd.amount,
            created_in_operation_id=transaction.created_in_operation_id,
            reverted_in_operation_id=None,
        )

        uow.session.add_all([debit_entry, credit_entry])
        uow.flush()

        return Result.ok(transaction)


def undo_operation(
    uow_factory: Callable[[], UnitOfWork],
    cmd: UndoOperationCommand,
) -> Result[int]:
    with uow_factory() as uow:
        session: Session = uow.session

        target: Optional[Operation] = (
            session.query(Operation)
            .filter(Operation.id == cmd.operation_id)
            .one_or_none()
        )

        if target is None:
            return Result.fail("operation not found")

        undo_op = Operation(type="undo")
        session.add(undo_op)
        uow.flush()

        session.query(Transaction).filter(
            Transaction.created_in_operation_id == target.id
        ).update(
            {"reverted_in_operation_id": undo_op.id}
        )

        session.query(Entry).filter(
            Entry.created_in_operation_id == target.id
        ).update(
            {"reverted_in_operation_id": undo_op.id}
        )

        uow.flush()

        return Result.ok(undo_op.id)


engine = create_engine("sqlite:///:memory:", future=True)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)

Base.metadata.create_all(engine)


def uow_factory() -> UnitOfWork:
    return UnitOfWork(SessionFactory)


with uow_factory() as uow:
    op = Operation(type="bootstrap")
    uow.session.add(op)
    uow.flush()

    cash = Account(
        name="cash",
        type=AccountType.asset,
        created_in_operation_id=op.id,
        reverted_in_operation_id=None,
    )

    expense = Account(
        name="groceries",
        type=AccountType.expense,
        created_in_operation_id=op.id,
        reverted_in_operation_id=None,
    )

    uow.session.add_all([cash, expense])
    uow.flush()


expense_result: Result[Transaction] = add_expense(
    uow_factory,
    AddExpenseCommand(
        description="buy food",
        amount=100,
        date=datetime.utcnow(),
    ),
)

if expense_result.is_ok:
    undo_result: Result[int] = undo_operation(
        uow_factory,
        UndoOperationCommand(
            operation_id=expense_result.value.created_in_operation_id,
        ),
    )
```

You asked:
How above bulk insert transaction now map to double entry bookkeeping

```python
T = TypeVar("T")

model_registry: Dict[str, Type] = {}
serde_policy_registry: Dict[str, SerdePolicy] = {}


class RegisteredBase(DeclarativeBase):
    __serde_policy_factory__: Callable[[Type], SerdePolicy]
    __serde_policy__: SerdePolicy

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        table = getattr(cls, "__tablename__", None)

        if table is None:
            return

        if "__policy_factory__" not in cls.__dict__:
            raise RuntimeError(f"{cls.__name__} must define __policy_factory__")

        policy = cls.__serde_policy_factory__(cls)
        cls.__serde_policy__ = policy
        model_registry[table] = cls
        serde_policy_registry[table] = policy


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OperationGroup(base):
    __tablename__ = "operation_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)



class Operation(base):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("operation_groups.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    before_state: Mapped[str | None] = mapped_column(String, nullable=True)
    after_state: Mapped[str | None] = mapped_column(String, nullable=True)

```
