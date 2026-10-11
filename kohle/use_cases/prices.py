from collections.abc import Collection

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    EmptyPriceSymbol,
    NotASecurityUnit,
    SetPriceSourceError,
    UnknownPricePlugin,
)
from kohle.domain.models import PriceBinding, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.price_services import set_price_binding_service
from kohle.services.unit_services import get_unit_by_identifier_service


class SetPriceSource(UnitOfWork[PriceBinding, SetPriceSourceError]):
    def execute(
        self, identifier: str, plugin_name: str, symbol: str, available_plugins: Collection[str]
    ) -> Result[PriceBinding, SetPriceSourceError]:
        def use_case(ctx: DbTransactionContext) -> Result[PriceBinding, SetPriceSourceError]:
            stripped = symbol.strip()
            if not stripped:
                return Result.err(EmptyPriceSymbol())
            if plugin_name not in available_plugins:
                return Result.err(UnknownPricePlugin(plugin_name, sorted(available_plugins)))

            unit_res = get_unit_by_identifier_service(ctx, identifier)
            if unit_res.is_err:
                return Result.err(unit_res.unwrap_err())
            unit = unit_res.unwrap()
            if unit.kind != UnitKind.security:
                return Result.err(NotASecurityUnit(identifier, unit.kind.value))

            return set_price_binding_service(ctx, unit.id, plugin_name, stripped).map_err(lambda e: e)

        return self._run(use_case)
