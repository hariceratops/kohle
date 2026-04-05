from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Callable, List, TypeVar
from kohle.core.result import Result
from kohle.infrastructure.infra_errors import InfrastructureError, UniqueViolation
from kohle.domain.models import Operation, OperationGroup


T = TypeVar("T")

class DbTransactionContext:
    def __init__(self, session: Session):
        self.session = session
        self.transaction_group = OperationGroup()
        self.session.add(self.transaction_group)
        self.session.flush()
        self.transaction_steps: List[Operation] = []

    def record_transaction_step(self, op: Operation):
        self.transaction_steps.append(op)

    def run(self, op: Callable[[Session], T]) -> Result[T, InfrastructureError]:
        try:
            value = op(self.session)
            self.session.flush()
            return Result.ok(value)

        except IntegrityError as e:
            constraint = getattr(e.orig, "args", [None])[0] or str(e)
            return Result.err(UniqueViolation(constraint=constraint))

        except Exception as e:
            return Result.err(InfrastructureError(str(e)))

