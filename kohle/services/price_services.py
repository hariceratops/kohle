from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.domain_errors import PriceError
from kohle.domain.models import Price, PriceBinding
from kohle.infrastructure.crud import crud_create, crud_retrieve, crud_update
from kohle.infrastructure.transaction_context import DbTransactionContext


@crud_retrieve
def price_bindings_service(
    ctx: DbTransactionContext, unit_ids: Sequence[int]
) -> Result[list[PriceBinding], PriceError]:
    def op(session: Session) -> list[PriceBinding]:
        return (
            session.query(PriceBinding)
            .filter(PriceBinding.unit_id.in_(unit_ids))
            .order_by(PriceBinding.unit_id)
            .all()
        )

    return ctx.run(op).map_err(lambda err: PriceError(str(err)))


@crud_create
def _create_price_binding_service(
    ctx: DbTransactionContext, unit_id: int, plugin_name: str, symbol: str
) -> Result[PriceBinding, PriceError]:
    def op(session: Session) -> PriceBinding:
        binding = PriceBinding(unit_id=unit_id, plugin_name=plugin_name, symbol=symbol)
        session.add(binding)
        return binding

    return ctx.run(op).map_err(lambda err: PriceError(str(err)))


@crud_update
def _update_price_binding_service(
    ctx: DbTransactionContext, binding_id: int, plugin_name: str, symbol: str
) -> Result[PriceBinding, PriceError]:
    def op(session: Session) -> PriceBinding:
        binding = session.get_one(PriceBinding, binding_id)
        binding.plugin_name = plugin_name
        binding.symbol = symbol
        return binding

    return ctx.run(op).map_err(lambda err: PriceError(str(err)))


def set_price_binding_service(
    ctx: DbTransactionContext, unit_id: int, plugin_name: str, symbol: str
) -> Result[PriceBinding, PriceError]:
    """Insert the unit's binding the first time, replace it after. An identical
    rebind writes nothing, so a replay leaves no OperationGroup."""
    existing_res = price_bindings_service(ctx, [unit_id])
    if existing_res.is_err:
        return Result.err(existing_res.unwrap_err())
    existing = existing_res.unwrap()
    if not existing:
        return _create_price_binding_service(ctx, unit_id, plugin_name, symbol)
    binding = existing[0]
    if binding.plugin_name == plugin_name and binding.symbol == symbol:
        return Result.ok(binding)
    return _update_price_binding_service(ctx, binding.id, plugin_name, symbol)


@crud_create
def add_price_service(
    ctx: DbTransactionContext, unit_id: int, price_date: date, price: Decimal, source: str
) -> Result[Price, PriceError]:
    def op(session: Session) -> Price:
        row = Price(unit_id=unit_id, price_date=price_date, price=price, source=source)
        session.add(row)
        return row

    return ctx.run(op).map_err(lambda err: PriceError(str(err)))


@crud_retrieve
def price_exists_service(
    ctx: DbTransactionContext, unit_id: int, price_date: date
) -> Result[bool, PriceError]:
    def op(session: Session) -> bool:
        return (
            session.query(Price.id)
            .filter(Price.unit_id == unit_id, Price.price_date == price_date)
            .first()
        ) is not None

    return ctx.run(op).map_err(lambda err: PriceError(str(err)))


@crud_retrieve
def latest_price_service(ctx: DbTransactionContext, unit_id: int) -> Result[Price | None, PriceError]:
    def op(session: Session) -> Price | None:
        return (
            session.query(Price)
            .filter(Price.unit_id == unit_id)
            .order_by(Price.price_date.desc())
            .first()
        )

    return ctx.run(op).map_err(lambda err: PriceError(str(err)))
