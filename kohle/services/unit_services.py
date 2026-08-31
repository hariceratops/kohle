from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.domain_errors import DuplicateUnit, UnitError, UnitNotFoundError
from kohle.domain.models import Unit, UnitKind
from kohle.infrastructure.crud import crud_create, crud_retrieve
from kohle.infrastructure.infra_errors import check_if_unique_constraint_failed
from kohle.infrastructure.transaction_context import DbTransactionContext


@crud_create
def add_unit_service(
    ctx: DbTransactionContext, identifier: str, name: str, kind: UnitKind
) -> Result[Unit, UnitError]:
    def op(session: Session) -> Unit:
        unit = Unit(identifier=identifier, name=name, kind=kind)
        session.add(unit)
        return unit

    return (
        ctx.run(op)
        .map_err(lambda err: (
            DuplicateUnit(identifier) if check_if_unique_constraint_failed(err, "units.identifier")
            else UnitError(str(err))
        ))
    )


@crud_retrieve
def get_unit_by_identifier_service(ctx: DbTransactionContext, identifier: str) -> Result[Unit, UnitError]:
    def op(session: Session) -> Unit | None:
        return session.query(Unit).filter(Unit.identifier == identifier).one_or_none()

    return (
        ctx.run(op)
        .map_err(lambda err: UnitError(str(err)))
        .and_then(lambda unit:
            Result.ok(unit)
            if unit is not None
            else Result.err(UnitNotFoundError(identifier))
        )
    )


@crud_retrieve
def list_units_service(ctx: DbTransactionContext) -> Result[list[Unit], UnitError]:
    def op(session: Session) -> list[Unit]:
        return session.query(Unit).order_by(Unit.identifier).all()

    return ctx.run(op).map_err(lambda err: UnitError(str(err)))
