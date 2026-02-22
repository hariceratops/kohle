# kohle/infrastructure/uow.py
from typing import Callable, TypeVar, Generic
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from kohle.core.result import Result
from kohle.infrastructure.infra_errors import UniqueViolation, InfrastructureError

T = TypeVar("T")

class UnitOfWork(Generic[T]):
    def __init__(self, session: Session):
        self.session = session

    def __enter__(self) -> "UnitOfWork":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.session.rollback()
        self.session.close()

    def run(self, op: Callable[[Session], T]) -> Result[T, InfrastructureError]:
        try:
            value = op(self.session)
            self.session.flush()  # triggers DB validation
            self.session.commit()
            return Result.ok(value)

        except IntegrityError as e:
            self.session.rollback()
            constraint = getattr(e.orig, "args", [None])[0] or str(e)
            return Result.err(UniqueViolation(constraint=constraint))

        except Exception as e:
            self.session.rollback()
            return Result.err(InfrastructureError(str(e)))

