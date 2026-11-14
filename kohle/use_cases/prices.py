from collections.abc import Collection, Mapping, Sequence
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
    NotAQuoteCurrency,
    NotASecurityUnit,
    PriceError,
    PriceRejection,
    RateNotQuotedInEur,
    SetPriceSourceError,
    UnknownPricePlugin,
    UnrequestedSymbol,
)
from kohle.domain.models import BASE_CURRENCY, Price, PriceBinding, Unit, UnitKind
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
from kohle.use_cases.journal import held_units


class SetPriceSource(UnitOfWork[PriceBinding, SetPriceSourceError]):
    def execute(
        self,
        identifier: str,
        plugin_name: str,
        symbol: str,
        available_plugins: Collection[str],
        quote_currency: str = BASE_CURRENCY,
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
            is_rate = unit.kind == UnitKind.currency and unit.identifier != BASE_CURRENCY
            if is_rate and quote_currency != BASE_CURRENCY:
                return Result.err(RateNotQuotedInEur(identifier, quote_currency))
            if unit.kind != UnitKind.security and not is_rate:
                return Result.err(NotASecurityUnit(identifier, unit.kind.value))

            if not is_rate and quote_currency != BASE_CURRENCY:
                quote_res = get_unit_by_identifier_service(ctx, quote_currency)
                if quote_res.is_err or quote_res.unwrap().kind != UnitKind.currency:
                    return Result.err(NotAQuoteCurrency(quote_currency))

            return set_price_binding_service(ctx, unit.id, plugin_name, stripped, quote_currency).map_err(
                lambda e: e
            )

        return self._run(use_case)


def oldest_close_first(stored: Mapping[str, Sequence[date | None]]) -> list[str]:
    """Symbols in the order a quota-limited plugin should spend requests. `stored`
    maps each symbol to the latest stored close date of each unit bound to it
    (None: no close). A symbol is as stale as its stalest unit; no close sorts
    before any date; ties break by symbol."""

    def key(symbol: str) -> tuple[bool, date, str]:
        dates = stored[symbol]
        oldest = None if None in dates else min(d for d in dates if d is not None)
        return (oldest is not None, oldest or date.min, symbol)

    return sorted(stored, key=key)


@dataclass(frozen=True, slots=True)
class PriceTargets:
    by_plugin: dict[str, dict[str, list[Unit]]]
    request_order: dict[str, list[str]]
    unbound: list[Unit]
    quote_currencies: dict[int, str]


class ListPriceTargets(UnitOfWork[PriceTargets, ListPriceTargetsError]):
    def execute(self) -> Result[PriceTargets, ListPriceTargetsError]:
        def use_case(ctx: DbTransactionContext) -> Result[PriceTargets, ListPriceTargetsError]:
            held_res = held_units(ctx)
            if held_res.is_err:
                return Result.err(held_res.unwrap_err())
            targets = [
                unit
                for unit in held_res.unwrap()
                if unit.kind == UnitKind.security
                or (unit.kind == UnitKind.currency and unit.identifier != BASE_CURRENCY)
            ]

            bindings_res = price_bindings_service(ctx, [unit.id for unit in targets])
            if bindings_res.is_err:
                return Result.err(bindings_res.unwrap_err())
            bindings = {binding.unit_id: binding for binding in bindings_res.unwrap()}

            # A currency whose every unit was spent on shares is not held, yet the shares
            # still need its rate to be valued.
            target_ids = {unit.id for unit in targets}
            quote_codes = {
                bindings[unit.id].quote_currency
                for unit in targets
                if unit.kind == UnitKind.security and unit.id in bindings
            } - {BASE_CURRENCY}
            extra: list[Unit] = []
            for code in sorted(quote_codes):
                currency_res = get_unit_by_identifier_service(ctx, code)
                if currency_res.is_err:
                    return Result.err(PriceError(str(currency_res.unwrap_err())))
                if currency_res.unwrap().id not in target_ids:
                    extra.append(currency_res.unwrap())
            if extra:
                extra_res = price_bindings_service(ctx, [unit.id for unit in extra])
                if extra_res.is_err:
                    return Result.err(extra_res.unwrap_err())
                bindings.update({binding.unit_id: binding for binding in extra_res.unwrap()})
                targets = sorted([*targets, *extra], key=lambda unit: unit.identifier)

            by_plugin: dict[str, dict[str, list[Unit]]] = {}
            unbound: list[Unit] = []
            quote_currencies: dict[int, str] = {}
            for unit in targets:
                binding = bindings.get(unit.id)
                if binding is None:
                    unbound.append(unit)
                else:
                    quote_currencies[unit.id] = binding.quote_currency
                    by_plugin.setdefault(binding.plugin_name, {}).setdefault(binding.symbol, []).append(unit)

            request_order: dict[str, list[str]] = {}
            for name, symbols in by_plugin.items():
                stored: dict[str, list[date | None]] = {}
                for symbol, units in symbols.items():
                    dates: list[date | None] = []
                    for unit in units:
                        latest_res = latest_price_service(ctx, unit.id)
                        if latest_res.is_err:
                            return Result.err(latest_res.unwrap_err())
                        latest = latest_res.unwrap()
                        dates.append(None if latest is None else latest.price_date)
                    stored[symbol] = dates
                request_order[name] = oldest_close_first(stored)
            return Result.ok(PriceTargets(by_plugin, request_order, unbound, quote_currencies))

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
            symbols = targets.request_order[name]
            # Two units may share a symbol; the first by identifier names its currency, and the
            # other unit's close is then refused by its own check.
            by_symbol = targets.by_plugin[name]
            quote_currencies = {
                symbol: targets.quote_currencies[min(by_symbol[symbol], key=lambda u: u.identifier).id]
                for symbol in symbols
            }
            fetched[name] = plugin.fetch_bound_closes(symbols, quote_currencies).map_err(lambda e: e)
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


def validate_close(close: Close, today: date, quote_currency: str = BASE_CURRENCY) -> PriceRejection | None:
    # is_finite() first: comparing NaN raises InvalidOperation, which would roll back every unit.
    if not close.price.is_finite() or close.price <= 0:
        return NonPositivePrice(close.price)
    if close.price_date > today:
        return FutureCloseDate(close.price_date, today)
    if close.currency != quote_currency:
        return NonBaseCurrency(close.currency, quote_currency)
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
                    else:
                        for unit in units:
                            rejection = validate_close(result, today, targets.quote_currencies[unit.id])
                            if rejection is not None:
                                outcomes.append(Unpriced(unit, name, symbol, rejection))
                                continue
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
                            added_res = add_price_service(
                                ctx, unit.id, result.price_date, result.price, name, result.currency
                            )
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
    ctx: DbTransactionContext, unit_id: int, as_of: date, max_age_days: int = 7
) -> Result[LatestClose, PriceError]:
    latest_res = latest_price_service(ctx, unit_id, on_or_before=as_of)
    if latest_res.is_err:
        return Result.err(latest_res.unwrap_err())
    close = latest_res.unwrap()
    if close is None:
        return Result.ok(NoClose())
    if (as_of - close.price_date).days <= max_age_days:
        return Result.ok(Fresh(close))
    return Result.ok(Stale(close))
