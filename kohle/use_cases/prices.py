from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    EmptyPriceSymbol,
    FutureCloseDate,
    ListPriceTargetsError,
    MissingCloseResult,
    NonBaseCurrency,
    NonPositivePrice,
    NotASecurityUnit,
    PriceError,
    PriceRejection,
    SetPriceSourceError,
    UnknownPricePlugin,
    UnrequestedSymbol,
)
from kohle.domain.models import Price, PriceBinding, Unit, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.plugin.price_plugin import (
    Close,
    PriceFetcherPlugin,
    PriceFetchError,
    PriceResult,
    Unavailable,
)
from kohle.services.price_services import (
    add_price_service,
    latest_price_service,
    price_bindings_service,
    price_exists_service,
    set_price_binding_service,
)
from kohle.services.unit_services import get_unit_by_identifier_service
from kohle.use_cases.journal import BASE_CURRENCY, held_units


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


@dataclass(frozen=True, slots=True)
class PriceTargets:
    # plugin name -> symbol -> the held units bound to that (plugin, symbol)
    by_plugin: dict[str, dict[str, list[Unit]]]
    unbound: list[Unit]


class ListPriceTargets(UnitOfWork[PriceTargets, ListPriceTargetsError]):
    def execute(self) -> Result[PriceTargets, ListPriceTargetsError]:
        def use_case(ctx: DbTransactionContext) -> Result[PriceTargets, ListPriceTargetsError]:
            held_res = held_units(ctx)
            if held_res.is_err:
                return Result.err(held_res.unwrap_err())
            securities = [unit for unit in held_res.unwrap() if unit.kind == UnitKind.security]

            bindings_res = price_bindings_service(ctx, [unit.id for unit in securities])
            if bindings_res.is_err:
                return Result.err(bindings_res.unwrap_err())
            bindings = {binding.unit_id: binding for binding in bindings_res.unwrap()}

            by_plugin: dict[str, dict[str, list[Unit]]] = {}
            unbound: list[Unit] = []
            for unit in securities:
                binding = bindings.get(unit.id)
                if binding is None:
                    unbound.append(unit)
                else:
                    by_plugin.setdefault(binding.plugin_name, {}).setdefault(binding.symbol, []).append(unit)
            return Result.ok(PriceTargets(by_plugin, unbound))

        return self._run(use_case)


FetchedCloses = dict[str, Result[dict[str, PriceResult], PriceFetchError | UnknownPricePlugin]]


def call_price_plugins(targets: PriceTargets, plugins: Mapping[str, PriceFetcherPlugin]) -> FetchedCloses:
    """Ask each bound plugin once for its own symbols. Runs outside any
    transaction. A plugin that raises is a bug and is not caught here."""
    fetched: FetchedCloses = {}
    for name in sorted(targets.by_plugin):
        plugin = plugins.get(name)
        if plugin is None:
            fetched[name] = Result.err(UnknownPricePlugin(name, sorted(plugins)))
        else:
            fetched[name] = plugin.fetch_latest_closes(sorted(targets.by_plugin[name])).map_err(lambda e: e)
    return fetched


@dataclass(frozen=True, slots=True)
class Priced:
    unit: Unit
    plugin_name: str
    symbol: str
    close: Price
    previous: Price | None


@dataclass(frozen=True, slots=True)
class AlreadyStored:
    unit: Unit
    plugin_name: str
    symbol: str
    price_date: date


@dataclass(frozen=True, slots=True)
class Unpriced:
    unit: Unit
    plugin_name: str
    symbol: str
    reason: Unavailable | PriceFetchError | UnknownPricePlugin | PriceRejection


@dataclass(frozen=True, slots=True)
class Unbound:
    unit: Unit


FetchOutcome = Priced | AlreadyStored | Unpriced | Unbound


@dataclass(frozen=True, slots=True)
class FetchReport:
    outcomes: list[FetchOutcome]
    ignored: list[UnrequestedSymbol]


def validate_close(close: Close, today: date) -> PriceRejection | None:
    # is_finite() first: comparing NaN raises InvalidOperation, which would roll back every unit.
    if not close.price.is_finite() or close.price <= 0:
        return NonPositivePrice(close.price)
    if close.price_date > today:
        return FutureCloseDate(close.price_date, today)
    if close.currency != BASE_CURRENCY:
        return NonBaseCurrency(close.currency, BASE_CURRENCY)
    return None


class AppendPrices(UnitOfWork[FetchReport, PriceError]):
    def execute(
        self, targets: PriceTargets, fetched: FetchedCloses, today: date
    ) -> Result[FetchReport, PriceError]:
        def use_case(ctx: DbTransactionContext) -> Result[FetchReport, PriceError]:
            outcomes: list[FetchOutcome] = [Unbound(unit) for unit in targets.unbound]
            ignored: list[UnrequestedSymbol] = []

            for name, symbols in targets.by_plugin.items():
                results_res = fetched[name]
                if results_res.is_err:
                    reason = results_res.unwrap_err()
                    outcomes.extend(
                        Unpriced(unit, name, symbol, reason)
                        for symbol, units in symbols.items()
                        for unit in units
                    )
                    continue
                results = results_res.unwrap()
                ignored.extend(UnrequestedSymbol(name, key) for key in results if key not in symbols)

                for symbol, units in symbols.items():
                    result = results.get(symbol)
                    if result is None:
                        outcomes.extend(Unpriced(unit, name, symbol, MissingCloseResult(symbol)) for unit in units)
                    elif isinstance(result, Unavailable):
                        outcomes.extend(Unpriced(unit, name, symbol, result) for unit in units)
                    elif (rejection := validate_close(result, today)) is not None:
                        outcomes.extend(Unpriced(unit, name, symbol, rejection) for unit in units)
                    else:
                        for unit in units:
                            # Checked before the insert: after one UNIQUE violation the
                            # rest of the transaction fails with PendingRollbackError.
                            exists_res = price_exists_service(ctx, unit.id, result.price_date)
                            if exists_res.is_err:
                                return Result.err(exists_res.unwrap_err())
                            if exists_res.unwrap():
                                outcomes.append(AlreadyStored(unit, name, symbol, result.price_date))
                                continue

                            previous_res = latest_price_service(ctx, unit.id)
                            if previous_res.is_err:
                                return Result.err(previous_res.unwrap_err())
                            added_res = add_price_service(ctx, unit.id, result.price_date, result.price, name)
                            if added_res.is_err:
                                return Result.err(added_res.unwrap_err())
                            outcomes.append(Priced(unit, name, symbol, added_res.unwrap(), previous_res.unwrap()))

            return Result.ok(FetchReport(sorted(outcomes, key=_unit_identifier), ignored))

        return self._run(use_case)


def _unit_identifier(outcome: FetchOutcome) -> str:
    return outcome.unit.identifier


@dataclass(frozen=True, slots=True)
class Fresh:
    close: Price


@dataclass(frozen=True, slots=True)
class Stale:
    close: Price


@dataclass(frozen=True, slots=True)
class NoClose:
    pass


LatestClose = Fresh | Stale | NoClose


def latest_close(
    ctx: DbTransactionContext, unit_id: int, today: date, max_age_days: int = 7
) -> Result[LatestClose, PriceError]:
    latest_res = latest_price_service(ctx, unit_id)
    if latest_res.is_err:
        return Result.err(latest_res.unwrap_err())
    close = latest_res.unwrap()
    if close is None:
        return Result.ok(NoClose())
    if (today - close.price_date).days <= max_age_days:
        return Result.ok(Fresh(close))
    return Result.ok(Stale(close))
