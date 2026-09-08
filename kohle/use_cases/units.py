from kohle.core.result import Result
from kohle.domain.domain_errors import EmptyUnitIdentifier, UnitError
from kohle.domain.models import Unit, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.unit_services import (
    add_unit_service,
    get_unit_by_identifier_service,
    list_units_service,
)


def get_or_create_unit(
    ctx: DbTransactionContext, identifier: str, name: str, kind: UnitKind
) -> Result[Unit, UnitError]:
    existing = get_unit_by_identifier_service(ctx, identifier)
    if existing.is_ok:
        return existing
    return add_unit_service(ctx, identifier, name, kind)


class AddUnit(UnitOfWork[Unit, UnitError]):
    def execute(self, identifier: str, name: str, kind: UnitKind) -> Result[Unit, UnitError]:
        def use_case(ctx: DbTransactionContext) -> Result[Unit, UnitError]:
            ident = identifier.strip()
            if not ident:
                return Result.err(EmptyUnitIdentifier())
            return add_unit_service(ctx, ident, name.strip() or ident, kind)

        return self._run(use_case)


class ListUnits(UnitOfWork[list[Unit], UnitError]):
    def execute(self) -> Result[list[Unit], UnitError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[Unit], UnitError]:
            return list_units_service(ctx)

        return self._run(use_case)
