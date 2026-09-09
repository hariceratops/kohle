from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.models import Operation, OperationGroup
from kohle.infrastructure.infra_errors import InfrastructureError, UniqueViolation

T = TypeVar("T")

class DbTransactionContext:
    def __init__(self, session: Session):
        self.session = session
        self.transaction_group: OperationGroup | None = None
        self.transaction_steps: list[Operation] = []

    def record_transaction_step(self, op: Operation):
        # The group is created here rather than in __init__ so a use case that
        # writes nothing leaves no group behind, and consecutive writes get
        # consecutive group ids with no gaps from intervening reads.
        if self.transaction_group is None:
            self.transaction_group = OperationGroup()
            self.session.add(self.transaction_group)
            self.session.flush()
        op.group_id = self.transaction_group.id
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

