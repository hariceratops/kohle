# kohle/infrastructure/uow.py
from typing import Callable, TypeVar, Generic
from sqlalchemy.orm import Session, sessionmaker
from kohle.core.result import Result
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.db.connection import session_local


T = TypeVar("T")
E = TypeVar("E")


class DbTransaction(Generic[T, E]):
    # todo type of maker
    def __init__(self, session: Session):
        self.session: Session = session
        self.ctx = DbTransactionContext(self.session)

    def execute(self, use_case: Callable[[DbTransactionContext], Result[T, E]]) -> Result[T, E]:
        try:
            result = use_case(self.ctx)
            if result.is_ok:
                self.session.add(self.ctx.transaction_group)
                for op in self.ctx.transaction_steps:
                    self.session.add(op)
                self.session.commit()
                return result
            else:
                self.session.rollback()
                return result

        except Exception as e:
            self.session.rollback()
            return Result.err(e)
        finally:
            self.session.close()


def unit_of_work(
    fn: Callable[..., Callable[[DbTransactionContext], Result[T, Exception]]]
) -> Callable[..., Result[T, Exception]]:
    def wrapper(*args, **kwargs):
        tx = DbTransaction(session_local())
        return tx.execute(lambda ctx: fn(*args, **kwargs)(ctx))
    return wrapper


class UnitOfWork(Generic[T, E]):
    # todo type of maker
    def __init__(self, session: Session):
        self._session = session

    def _run(self, fn: Callable[[DbTransactionContext], Result[T, E]]) -> Result[T, E]:
        tx = DbTransaction(self._session)
        return tx.execute(fn)

