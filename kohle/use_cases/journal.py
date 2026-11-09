from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import assert_never
from uuid import uuid4

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    BalanceError,
    BaseCurrencyAsCrossUnit,
    ConversionBetweenCurrencies,
    CurrencyInflowWithoutRate,
    CurrencyLineNotAtPar,
    DuplicateReferenceInStatement,
    EmptyEntry,
    EndDatePrecedesStartDateError,
    ImportStatementError,
    InvalidDateError,
    JournalError,
    MalformedStatementRow,
    MissingInstrumentAccount,
    NonPositiveQuantity,
    NotACurrencyUnit,
    NotASecurityUnit,
    PostingToNonLeafAccount,
    QueryJournalByPeriodError,
    RecordEntryError,
    StatementError,
    UnbalancedEntry,
    UnitNotFoundError,
    UnknownInstruments,
)
from kohle.domain.models import (
    BASE_CURRENCY,
    AccountType,
    JournalEntry,
    JournalLine,
    Unit,
    UnitKind,
)
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.plugin.importer_plugin import CashRow, SecurityRow, StatementRow
from kohle.services.account_services import (
    account_has_children_service,
    add_account_service,
    descendant_account_ids_service,
    get_account_by_name_service,
    list_accounts_service,
)
from kohle.services.classification_services import add_classification_service
from kohle.services.journal_services import (
    Counterparty,
    LineSpec,
    account_lines_service,
    add_journal_entry_service,
    existing_references_service,
    query_lines_by_period_service,
)
from kohle.services.unit_services import (
    get_unit_by_identifier_service,
    units_by_id_service,
)
from kohle.use_cases.accounts import PEOPLE_ROOT as PEOPLE_ROOT
from kohle.use_cases.accounts import balance_sheet_accounts
from kohle.use_cases.lots import line_costs
from kohle.use_cases.rules import compile_rules, match_rule, stored_rules
from kohle.use_cases.units import get_or_create_unit

_PRICE_SCALE = Decimal("0.00000001")
UNCLASSIFIED_EXPENSE = "Unclassified Expense"
UNCLASSIFIED_INCOME = "Unclassified Income"


def parse_date(input_date: str) -> Result[date, InvalidDateError]:
    try:
        return Result.ok(date.fromisoformat(input_date))
    except ValueError:
        return Result.err(InvalidDateError(input_date))


def _optional_str(value: str | None) -> str | None:
    """`''` and `'   '` are the same fact as absent, and a placeholder would be
    a value a rule could match (design §3.1)."""
    if value is None:
        return None
    return value.strip() or None


def _get_or_create_account(
    ctx: DbTransactionContext, name: str, account_type: AccountType
):
    existing = get_account_by_name_service(ctx, name)
    if existing.is_ok:
        return existing
    return add_account_service(ctx, name, account_type)


def validate_lines(
    ctx: DbTransactionContext, lines: list[LineSpec]
) -> JournalError | None:
    if len(lines) < 2:
        return EmptyEntry()

    invalid = _validate_price_currencies(ctx, lines)
    if invalid:
        return invalid

    for line in lines:
        has_children = account_has_children_service(ctx, line.account_id)
        if has_children.is_err:
            return JournalError(str(has_children.unwrap_err()))
        if has_children.unwrap():
            return PostingToNonLeafAccount(line.account_id)

    return None


def _validate_price_currencies(ctx: DbTransactionContext, lines: list[LineSpec]) -> JournalError | None:
    """Balance within each price currency, the base currency first. The line
    rules run, and the unit lookup is made, only when some line states a total
    or names a price currency, so an entry in the base currency alone is
    checked and refused exactly as it always was."""
    for line in lines:
        if (line.cost is not None or line.price_unit_id is not None) and line.quantity <= 0:
            return NonPositiveQuantity(line.quantity)

    priced = sorted({line.price_unit_id for line in lines if line.price_unit_id is not None})
    units: dict[int, Unit] = {}
    if priced:
        units_res = units_by_id_service(ctx, priced + [line.unit_id for line in lines])
        if units_res.is_err:
            return JournalError(str(units_res.unwrap_err()))
        units = units_res.unwrap()

        for line in lines:
            if line.price_unit_id is None:
                continue
            currency = units[line.price_unit_id].identifier
            if line.unit_id == line.price_unit_id:
                if line.unit_price != 1 or line.cost is not None:
                    return CurrencyLineNotAtPar(currency)
            elif units[line.unit_id].kind is UnitKind.currency:
                return ConversionBetweenCurrencies(units[line.unit_id].identifier, currency)

        credited = [(line, line.price_unit_id) for line in lines if line.price_unit_id is not None and not line.is_debit]
        if credited:
            accounts_res = list_accounts_service(ctx)
            if accounts_res.is_err:
                return JournalError(str(accounts_res.unwrap_err()))
            accounts = {account.id: account for account in accounts_res.unwrap()}
            for line, priced_in in credited:
                account = accounts[line.account_id]
                if line.unit_id != priced_in or account.type not in (AccountType.asset, AccountType.liability):
                    return CurrencyInflowWithoutRate(account.name, units[priced_in].identifier)

    for price_unit_id in [None, *priced]:
        in_currency = [line for line in lines if line.price_unit_id == price_unit_id]
        debits = sum((line.value for line in in_currency if line.is_debit), Decimal(0))
        credits = sum((line.value for line in in_currency if not line.is_debit), Decimal(0))
        if debits != credits:
            return UnbalancedEntry(debits, credits, None if price_unit_id is None else units[price_unit_id].identifier)
    return None


def post_entry(
    ctx: DbTransactionContext,
    entry_date: date,
    reference: str,
    description: str,
    lines: list[LineSpec],
    counterparty: Counterparty | None = None,
) -> Result[JournalEntry, JournalError]:
    invalid = validate_lines(ctx, lines)
    if invalid:
        return Result.err(invalid)
    return add_journal_entry_service(ctx, entry_date, reference, description, lines, counterparty)


class RecordJournalEntry(UnitOfWork[JournalEntry, JournalError]):
    def execute(
        self,
        entry_date: date,
        reference: str,
        description: str,
        lines: Iterable[LineSpec],
    ) -> Result[JournalEntry, JournalError]:
        def use_case(ctx: DbTransactionContext) -> Result[JournalEntry, JournalError]:
            return post_entry(ctx, entry_date, reference, description, list(lines))

        return self._run(use_case)


@dataclass(frozen=True, slots=True)
class Total:
    """The whole euro value of a holding line, stated rather than derived.

    A remittance of 90,000 INR for 1,000 EUR has no terminating per-unit
    rate, so only the total is exact (design §2.1).
    """

    amount: Decimal


@dataclass(frozen=True, slots=True)
class CurrencySide:
    """The currency the side without a unit flag carries at par, and in which
    the unit's price or total is stated.

    A value of its own, like `CrossUnitLine`, so that what a later rate needs
    (a currency to apply it to) cannot be supplied without it.
    """

    identifier: str
    rate: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CrossUnitLine:
    """Which side of `record` carries a non-base unit, at what price.

    One value rather than three independent parameters: identifier, price
    and side are mutually dependent — a price without a unit is meaningless,
    a side without a unit is meaningless — and separate `| None` parameters
    would make those invalid combinations representable at the use-case
    boundary, forcing a re-rejection of what the CLI already rejected.
    """

    identifier: str
    price: Decimal | Total
    is_debit: bool


def _cross_unit_lines(
    *,
    holding_account_id: int,
    holding_unit_id: int,
    quantity: Decimal,
    unit_price: Decimal | Total,
    cash_account_id: int,
    cash_unit_id: int,
    into_holding: bool,
    paid_in_currency: bool = False,
) -> list[LineSpec]:
    """Shared by `record` and imported trades so the cost fold sees one
    definition of a trade. With `paid_in_currency`, `cash_unit_id` is the
    currency paid, and both lines are priced in it: the euro value of the trade
    is then the cost of the currency's lots, derived when the ledger is read."""
    price_unit_id = cash_unit_id if paid_in_currency else None
    if isinstance(unit_price, Total):
        total = unit_price.amount
        per_unit = (total / quantity).quantize(_PRICE_SCALE)
        return [
            LineSpec(holding_account_id, holding_unit_id, quantity, per_unit, is_debit=into_holding, cost=total, price_unit_id=price_unit_id),
            LineSpec(cash_account_id, cash_unit_id, total, Decimal(1), is_debit=not into_holding, price_unit_id=price_unit_id),
        ]
    if paid_in_currency:
        # Quantised so that what is validated is what is stored.
        value = (quantity * unit_price).quantize(_PRICE_SCALE)
        return [
            LineSpec(holding_account_id, holding_unit_id, quantity, unit_price, is_debit=into_holding, cost=value, price_unit_id=price_unit_id),
            LineSpec(cash_account_id, cash_unit_id, value, Decimal(1), is_debit=not into_holding, price_unit_id=price_unit_id),
        ]
    return [
        LineSpec(holding_account_id, holding_unit_id, quantity, unit_price, is_debit=into_holding),
        LineSpec(cash_account_id, cash_unit_id, quantity * unit_price, Decimal(1), is_debit=not into_holding),
    ]


class RecordSimpleEntry(UnitOfWork[JournalEntry, RecordEntryError]):
    """The `record` CLI command's use case: a two-line entry, base-currency
    or cross-unit.

    A sibling of RecordJournalEntry, not a wrapper around it — UnitOfWork
    closes its session per run, so calling one use case from another would
    split the name lookups and the posting into two transactions.
    """

    def execute(
        self,
        entry_date: date,
        description: str,
        quantity: Decimal,
        from_account: str,
        to_account: str,
        cross: CrossUnitLine | None = None,
        currency_side: CurrencySide | None = None,
    ) -> Result[JournalEntry, RecordEntryError]:
        def use_case(ctx: DbTransactionContext) -> Result[JournalEntry, RecordEntryError]:
            from_res = get_account_by_name_service(ctx, from_account)
            if from_res.is_err:
                return Result.err(from_res.unwrap_err())
            to_res = get_account_by_name_service(ctx, to_account)
            if to_res.is_err:
                return Result.err(to_res.unwrap_err())

            base_unit_res = get_or_create_unit(ctx, BASE_CURRENCY, "Euro", UnitKind.currency)
            if base_unit_res.is_err:
                return Result.err(base_unit_res.unwrap_err())

            from_account_obj = from_res.unwrap()
            to_account_obj = to_res.unwrap()
            base_unit_id = base_unit_res.unwrap().id

            currency = None
            if currency_side is not None:
                currency_res = get_unit_by_identifier_service(ctx, currency_side.identifier)
                if currency_res.is_err:
                    return Result.err(currency_res.unwrap_err())
                currency = currency_res.unwrap()
                if currency.kind is not UnitKind.currency or currency.identifier == BASE_CURRENCY:
                    return Result.err(NotACurrencyUnit(currency.identifier, currency.kind.value))

            if currency_side is not None and currency is not None and currency_side.rate is not None:
                if cross is None:
                    amount = quantity
                elif isinstance(cross.price, Total):
                    amount = cross.price.amount
                else:
                    amount = (quantity * cross.price).quantize(_PRICE_SCALE)
                # Quantised so that what is validated is what is stored.
                value = (amount * currency_side.rate).quantize(_PRICE_SCALE)
                arriving = LineSpec(to_account_obj.id, currency.id, amount, currency_side.rate, is_debit=True, cost=value)
                if cross is None:
                    lines = [arriving, LineSpec(from_account_obj.id, currency.id, amount, currency_side.rate, is_debit=False, cost=value)]
                else:
                    sold_res = get_unit_by_identifier_service(ctx, cross.identifier)
                    if sold_res.is_err:
                        return Result.err(sold_res.unwrap_err())
                    per_unit = (value / quantity).quantize(_PRICE_SCALE)
                    lines = [
                        arriving,
                        LineSpec(from_account_obj.id, sold_res.unwrap().id, quantity, per_unit, is_debit=False, cost=value),
                    ]
            elif cross is None and currency is not None:
                lines = [
                    LineSpec(to_account_obj.id, currency.id, quantity, Decimal(1), is_debit=True, price_unit_id=currency.id),
                    LineSpec(from_account_obj.id, currency.id, quantity, Decimal(1), is_debit=False, price_unit_id=currency.id),
                ]
            elif cross is None:
                lines = [
                    LineSpec(to_account_obj.id, base_unit_id, quantity, Decimal(1), is_debit=True),
                    LineSpec(from_account_obj.id, base_unit_id, quantity, Decimal(1), is_debit=False),
                ]
            else:
                if cross.identifier == BASE_CURRENCY:
                    return Result.err(BaseCurrencyAsCrossUnit())

                cross_unit_res = get_unit_by_identifier_service(ctx, cross.identifier)
                if cross_unit_res.is_err:
                    return Result.err(cross_unit_res.unwrap_err())
                cross_unit_id = cross_unit_res.unwrap().id

                cross_account = to_account_obj if cross.is_debit else from_account_obj
                base_account = from_account_obj if cross.is_debit else to_account_obj

                lines = _cross_unit_lines(
                    holding_account_id=cross_account.id,
                    holding_unit_id=cross_unit_id,
                    quantity=quantity,
                    unit_price=cross.price,
                    cash_account_id=base_account.id,
                    cash_unit_id=base_unit_id if currency is None else currency.id,
                    into_holding=cross.is_debit,
                    paid_in_currency=currency is not None,
                )

            entry_res = post_entry(ctx, entry_date, uuid4().hex, description, lines)
            if entry_res.is_err:
                return Result.err(entry_res.unwrap_err())
            return Result.ok(entry_res.unwrap())

        return self._run(use_case)


@dataclass(frozen=True, slots=True)
class LineInput:
    """The name-shaped twin of LineSpec: the CLI holds account and unit
    *names* and cannot resolve them to ids without a Session, and LineSpec
    needs ids, so this carries a line across that boundary (design §5.2)."""

    account_name: str
    quantity: Decimal
    unit_identifier: str
    unit_price: Decimal | Total
    is_debit: bool
    price_currency: str | None = None


class RecordSplitEntry(UnitOfWork[JournalEntry, RecordEntryError]):
    """The `record-split` CLI command's use case: an n-line entry, every
    line given in full rather than derived.

    A sibling of RecordSimpleEntry and RecordJournalEntry, not a wrapper —
    see RecordSimpleEntry's docstring for why. Account and unit names are
    resolved strictly, no auto-creation, so a typo is an error rather than a
    silently created account or unit — except the base currency, which is
    auto-created on first use exactly as it is for RecordSimpleEntry and
    ImportStatement: BASE_CURRENCY is a module constant the user never types,
    so auto-creating it cannot mask a typo, and without this a fresh
    install's first `record-split` fails with "Unit EUR not found" for a
    unit the user did not name.
    """

    def execute(
        self, entry_date: date, description: str, lines: Iterable[LineInput]
    ) -> Result[JournalEntry, RecordEntryError]:
        def use_case(ctx: DbTransactionContext) -> Result[JournalEntry, RecordEntryError]:
            specs: list[LineSpec] = []
            for line in lines:
                account_res = get_account_by_name_service(ctx, line.account_name)
                if account_res.is_err:
                    return Result.err(account_res.unwrap_err())
                unit_res = (
                    get_or_create_unit(ctx, BASE_CURRENCY, "Euro", UnitKind.currency)
                    if line.unit_identifier == BASE_CURRENCY
                    else get_unit_by_identifier_service(ctx, line.unit_identifier)
                )
                if unit_res.is_err:
                    return Result.err(unit_res.unwrap_err())
                unit = unit_res.unwrap()

                price_unit_id = None
                if line.price_currency is not None and line.price_currency != BASE_CURRENCY:
                    currency_res = get_unit_by_identifier_service(ctx, line.price_currency)
                    if currency_res.is_err:
                        return Result.err(currency_res.unwrap_err())
                    currency = currency_res.unwrap()
                    if currency.kind is not UnitKind.currency:
                        return Result.err(NotACurrencyUnit(currency.identifier, currency.kind.value))
                    price_unit_id = currency.id

                cost = None
                if isinstance(line.unit_price, Total):
                    cost = line.unit_price.amount
                    unit_price = (cost / line.quantity).quantize(_PRICE_SCALE)
                else:
                    unit_price = line.unit_price
                    if price_unit_id is not None and unit.id != price_unit_id:
                        # Quantised so that what is validated is what is stored.
                        cost = (line.quantity * unit_price).quantize(_PRICE_SCALE)
                specs.append(
                    LineSpec(
                        account_res.unwrap().id,
                        unit.id,
                        line.quantity,
                        unit_price,
                        line.is_debit,
                        cost=cost,
                        price_unit_id=price_unit_id,
                    )
                )

            entry_res = post_entry(ctx, entry_date, uuid4().hex, description, specs)
            if entry_res.is_err:
                return Result.err(entry_res.unwrap_err())
            return Result.ok(entry_res.unwrap())

        return self._run(use_case)


def validate_statement(rows: Sequence[StatementRow]) -> StatementError | None:
    first_seen: dict[str, int] = {}
    for number, row in enumerate(rows, start=1):
        reference = (row.reference or "").strip()
        if not reference:
            return MalformedStatementRow(number, "reference", "is empty")
        if reference in first_seen:
            return DuplicateReferenceInStatement(reference, first_seen[reference], number)
        first_seen[reference] = number
        match row:
            case CashRow():
                pass
            case SecurityRow():
                problem = _security_row_problem(row)
                if problem is not None:
                    return MalformedStatementRow(number, *problem)
            case _:
                assert_never(row)
    return None


def _security_row_problem(row: SecurityRow) -> tuple[str, str] | None:
    # The type is a promise a plugin can break (an empty cell becomes None or
    # NaN), and each of these would otherwise post a wrong cost basis or fail
    # far from the cause.
    if not (row.instrument_identifier or "").strip():
        return "instrument_identifier", "is empty"
    if row.unit_price is None or not row.unit_price.is_finite() or row.unit_price <= 0:
        return "unit_price", f"must be a positive number, got {row.unit_price}"
    if row.quantity is None or not row.quantity.is_finite() or row.quantity == 0:
        return "quantity", f"must be a non-zero number, got {row.quantity}"
    return None


class ImportStatement(UnitOfWork[int, ImportStatementError]):
    """Statement rows become balanced entries, each posted to the account its
    first matching rule names, or to an unclassified bucket when none matches.
    Every row's decision is recorded, matched or not."""

    def execute(
        self,
        cash_account_name: str,
        rows: Sequence[StatementRow],
        instrument_account_name: str | None = None,
    ) -> Result[int, ImportStatementError]:
        def use_case(ctx: DbTransactionContext) -> Result[int, ImportStatementError]:
            statement_error = validate_statement(rows)
            if statement_error is not None:
                return Result.err(statement_error)

            # Decided by the statement's shape, not by what is already
            # imported, so the same input always has the same requirement.
            if instrument_account_name is None and any(isinstance(row, SecurityRow) for row in rows):
                return Result.err(MissingInstrumentAccount())

            account_res = get_account_by_name_service(ctx, cash_account_name)
            if account_res.is_err:
                return Result.err(account_res.unwrap_err())
            account = account_res.unwrap()

            instrument_account = None
            if instrument_account_name is not None:
                instrument_res = get_account_by_name_service(ctx, instrument_account_name)
                if instrument_res.is_err:
                    return Result.err(instrument_res.unwrap_err())
                instrument_account = instrument_res.unwrap()

            # The cash account scopes every row's reference, trades included:
            # it is the one account all rows touch, so re-importing a broker
            # file under another instrument account is still a no-op.
            keyed = [(row, f"{account.id}:{row.reference.strip()}") for row in rows]

            existing_res = existing_references_service(ctx, [reference for _, reference in keyed])
            if existing_res.is_err:
                return Result.err(existing_res.unwrap_err())
            existing = existing_res.unwrap()

            new_rows = [(row, reference) for row, reference in keyed if reference not in existing]
            if not new_rows:
                return Result.ok(0)

            units: dict[str, int] = {}
            missing: list[str] = []
            identifiers = dict.fromkeys(
                row.instrument_identifier for row, _ in new_rows if isinstance(row, SecurityRow)
            )
            for identifier in identifiers:
                instrument_unit_res = get_unit_by_identifier_service(ctx, identifier)
                if instrument_unit_res.is_err:
                    unit_error = instrument_unit_res.unwrap_err()
                    if isinstance(unit_error, UnitNotFoundError):
                        missing.append(identifier)
                        continue
                    return Result.err(unit_error)
                instrument_unit = instrument_unit_res.unwrap()
                if instrument_unit.kind != UnitKind.security:
                    return Result.err(NotASecurityUnit(identifier, instrument_unit.kind.value))
                units[identifier] = instrument_unit.id
            if missing:
                return Result.err(UnknownInstruments(sorted(missing)))

            # After the early return: a re-import must make no write call, or
            # it would leave an OperationGroup behind.
            unit_res = get_or_create_unit(ctx, BASE_CURRENCY, "Euro", UnitKind.currency)
            if unit_res.is_err:
                return Result.err(unit_res.unwrap_err())
            unit_id = unit_res.unwrap().id

            expense_res = _get_or_create_account(ctx, UNCLASSIFIED_EXPENSE, AccountType.expense)
            if expense_res.is_err:
                return Result.err(expense_res.unwrap_err())
            income_res = _get_or_create_account(ctx, UNCLASSIFIED_INCOME, AccountType.income)
            if income_res.is_err:
                return Result.err(income_res.unwrap_err())
            expense_id = expense_res.unwrap().id
            income_id = income_res.unwrap().id

            # Loaded and compiled once for the whole statement: a query per row
            # is N x M, and re.compile per row recompiles a fixed rule set.
            rules_res = stored_rules(ctx)
            if rules_res.is_err:
                return Result.err(rules_res.unwrap_err())
            compiled = compile_rules(rules_res.unwrap())

            imported = 0
            for row, reference in new_rows:
                match row:
                    case CashRow():
                        amount = row.amount
                        magnitude = abs(amount)
                        counterparty = Counterparty(
                            _optional_str(row.counterparty_name),
                            _optional_str(row.counterparty_iban),
                        )
                        matched = match_rule(compiled, row.description, counterparty, amount)
                        # A matched rule whose account has since gained a child fails
                        # the import loudly through validate_lines, rather than falling
                        # back to the bucket: a silent fallback would leave the user's
                        # rules quietly disabled with nothing saying why.
                        counterpart_id = matched.account_id if matched else (
                            expense_id if amount < 0 else income_id
                        )
                        lines = [
                            LineSpec(
                                account_id=account.id,
                                unit_id=unit_id,
                                quantity=magnitude,
                                unit_price=Decimal(1),
                                is_debit=amount > 0,
                            ),
                            LineSpec(
                                account_id=counterpart_id,
                                unit_id=unit_id,
                                quantity=magnitude,
                                unit_price=Decimal(1),
                                is_debit=amount < 0,
                            ),
                        ]
                        entry_res = post_entry(
                            ctx, row.entry_date, reference, row.description, lines, counterparty
                        )
                        if entry_res.is_err:
                            return Result.err(entry_res.unwrap_err())

                        # Written on both paths, so what the engine decided has one
                        # place to be read from whether or not a rule fired. The two
                        # account columns hold the same value here and diverge only
                        # when a human corrects the line.
                        classification_res = add_classification_service(
                            ctx,
                            journal_entry_id=entry_res.unwrap().id,
                            proposed_account_id=counterpart_id,
                            matched_rule_id=matched.rule_id if matched else None,
                            final_account_id=counterpart_id,
                        )
                        if classification_res.is_err:
                            return Result.err(classification_res.unwrap_err())
                    case SecurityRow():
                        # Both accounts are named on the command line, so there
                        # is nothing for a rule to decide and no classification.
                        assert instrument_account is not None
                        trade_lines = _cross_unit_lines(
                            holding_account_id=instrument_account.id,
                            holding_unit_id=units[row.instrument_identifier],
                            quantity=abs(row.quantity),
                            unit_price=row.unit_price,
                            cash_account_id=account.id,
                            cash_unit_id=unit_id,
                            into_holding=row.quantity > 0,
                        )
                        trade_res = post_entry(ctx, row.entry_date, reference, row.description, trade_lines)
                        if trade_res.is_err:
                            return Result.err(trade_res.unwrap_err())
                    case _:
                        assert_never(row)
                imported += 1

            return Result.ok(imported)

        return self._run(use_case)


class QueryJournalByPeriod(UnitOfWork[list[JournalLine], QueryJournalByPeriodError]):
    def execute(
        self, account_name: str, start_date_str: str, end_date_str: str
    ) -> Result[list[JournalLine], QueryJournalByPeriodError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[JournalLine], QueryJournalByPeriodError]:
            account_res = get_account_by_name_service(ctx, account_name)
            if account_res.is_err:
                return Result.err(account_res.unwrap_err())

            start_res = parse_date(start_date_str)
            if start_res.is_err:
                return Result.err(start_res.unwrap_err())
            end_res = parse_date(end_date_str)
            if end_res.is_err:
                return Result.err(end_res.unwrap_err())

            start_date = start_res.unwrap()
            end_date = end_res.unwrap()
            if start_date >= end_date:
                return Result.err(EndDatePrecedesStartDateError(start_date_str, end_date_str))

            return query_lines_by_period_service(ctx, account_res.unwrap().id, start_date, end_date)

        return self._run(use_case)


@dataclass(frozen=True, slots=True)
class UnitBalance:
    unit_identifier: str
    quantity: Decimal
    average_cost: Decimal | None
    unit_id: int
    kind: UnitKind | None = None

    @property
    def at_cost(self) -> Decimal:
        """`quantity * average_cost`, not `sum(line.value)` — the two coincide
        for a euro-only ledger and diverge the moment a holding is partly sold,
        because the sale's counter-line is priced at the sale price, not the
        cost basis, and so carries the realised gain invisibly (design §9.3).
        `average_cost` is `None` only when `quantity` is 0, which contributes 0."""
        if self.average_cost is None:
            return Decimal(0)
        return self.quantity * self.average_cost


class _RunningCost:
    """Per-unit accumulator for the moving-average cost fold (design §6.4)."""

    __slots__ = ("basis", "kind", "quantity", "unit_id")

    def __init__(self, unit_id: int, kind: UnitKind) -> None:
        self.unit_id = unit_id
        self.kind = kind
        self.basis = Decimal(0)
        self.quantity = Decimal(0)

    def apply(self, line: JournalLine, cost: Decimal | None) -> None:
        """`cost` is the line's euro value from the currency lots, when it has
        one; the basis then moves by exactly that, so a currency's basis is its
        FIFO cost."""
        if line.is_debit:
            self.basis += line.value if cost is None else cost
            self.quantity += line.quantity
        elif cost is not None:
            self.basis -= cost
            self.quantity -= line.quantity
        else:
            if self.quantity == 0:
                # Net-short in a non-base unit: basis/quantity is undefined.
                # Falling back to the line's own price only keeps the fold
                # from dividing by zero — it is not a claim that this is
                # meaningful accounting, and should not be "improved" into
                # something that looks more principled than it is.
                self.basis -= line.value
            else:
                self.basis -= line.quantity * (self.basis / self.quantity)
            self.quantity -= line.quantity

    @property
    def average_cost(self) -> Decimal | None:
        if self.quantity == 0:
            return None
        return self.basis / self.quantity


def aggregate_by_unit(lines: Iterable[JournalLine], costs: Mapping[int, Decimal] | None = None) -> list[UnitBalance]:
    """Moving-average cost fold, one accumulator per unit. `costs` maps a line id
    to the euro value `lots.line_costs` derived for it: a currency's lines, and
    the lines paid for with it, take it in place of a price.

    Order-dependent: consumes the caller's ordering as-is and must not sort,
    since `account_lines_service`'s `(entry_date, line id)` order is what
    makes the running average correct (design §6.4).
    """
    running: dict[str, _RunningCost] = {}
    for line in lines:
        _apply(running, line, costs)
    return _unit_balances(running)


def _apply(running: dict[str, _RunningCost], line: JournalLine, costs: Mapping[int, Decimal] | None) -> None:
    identifier = line.unit.identifier
    if identifier not in running:
        running[identifier] = _RunningCost(line.unit_id, line.unit.kind)
    running[identifier].apply(line, costs.get(line.id) if costs else None)


def _unit_balances(running: dict[str, _RunningCost]) -> list[UnitBalance]:
    return [
        UnitBalance(identifier, cost.quantity, cost.average_cost, cost.unit_id, cost.kind)
        for identifier, cost in running.items()
    ]


def aggregate_by_unit_through(
    lines: Iterable[JournalLine], dates: Iterable[date], costs: Mapping[int, Decimal] | None = None
) -> list[list[UnitBalance]]:
    """`aggregate_by_unit` of the lines dated on or before each date, in one
    pass: re-folding a prefix per date is quadratic. `lines` must be in ledger
    order and `dates` ascending."""
    running: dict[str, _RunningCost] = {}
    pending = iter(lines)
    held = next(pending, None)
    snapshots: list[list[UnitBalance]] = []
    for day in dates:
        while held is not None and held.entry.entry_date <= day:
            _apply(running, held, costs)
            held = next(pending, None)
        snapshots.append(_unit_balances(running))
    return snapshots


def account_balance(ctx: DbTransactionContext, account_id: int) -> Result[list[UnitBalance], BalanceError]:
    """The balance of an account and its descendants, by unit — the fold
    `QueryAccountBalance` runs for `balance`, factored out so `WhoOwesWhat`
    can call it once per person account without a name lookup (design §7.1,
    §9.2)."""
    descendants_res = descendant_account_ids_service(ctx, account_id)
    if descendants_res.is_err:
        return Result.err(descendants_res.unwrap_err())

    lines_res = account_lines_service(ctx, descendants_res.unwrap())
    if lines_res.is_err:
        return Result.err(lines_res.unwrap_err())
    lines = lines_res.unwrap()

    costs_res = line_costs(ctx, lines)
    if costs_res.is_err:
        return Result.err(costs_res.unwrap_err())

    return Result.ok(aggregate_by_unit(lines, costs_res.unwrap()))


def held_units(ctx: DbTransactionContext) -> Result[list[Unit], BalanceError]:
    """Units with a nonzero net quantity across every account, by identifier.

    Folded in Python rather than summed in SQL: SQLite stores NUMERIC as REAL,
    so a SQL SUM of 0.1 + 0.2 - 0.3 is not zero and a sold-out fractional
    position would count as held for ever."""
    accounts_res = list_accounts_service(ctx)
    if accounts_res.is_err:
        return Result.err(accounts_res.unwrap_err())

    lines_res = account_lines_service(ctx, [account.id for account in accounts_res.unwrap()])
    if lines_res.is_err:
        return Result.err(lines_res.unwrap_err())
    lines = lines_res.unwrap()

    units = {line.unit.identifier: line.unit for line in lines}
    held = [
        units[balance.unit_identifier]
        for balance in aggregate_by_unit(lines)
        if balance.quantity != 0
    ]
    return Result.ok(sorted(held, key=lambda unit: unit.identifier))


class QueryAccountBalance(UnitOfWork[list[UnitBalance], BalanceError]):
    def execute(self, account_name: str) -> Result[list[UnitBalance], BalanceError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[UnitBalance], BalanceError]:
            account_res = get_account_by_name_service(ctx, account_name)
            if account_res.is_err:
                return Result.err(account_res.unwrap_err())

            return account_balance(ctx, account_res.unwrap().id)

        return self._run(use_case)


def _at_cost(balances: Iterable[UnitBalance]) -> Decimal:
    """Sum of `UnitBalance.at_cost`, which documents why it is not `sum(line.value)`."""
    return sum((b.at_cost for b in balances), Decimal(0))


@dataclass(frozen=True, slots=True)
class NetWorthReport:
    own: list[UnitBalance]
    receivables: list[UnitBalance]

    @property
    def own_at_cost(self) -> Decimal:
        return _at_cost(self.own)

    @property
    def receivables_at_cost(self) -> Decimal:
        return _at_cost(self.receivables)

    @property
    def net_worth_at_cost(self) -> Decimal:
        return self.own_at_cost + self.receivables_at_cost


@dataclass(frozen=True, slots=True)
class NetWorthLines:
    own: list[JournalLine]
    receivables: list[JournalLine]
    # A line's cost depends only on earlier lines, so one mapping serves every
    # sample date of the history.
    costs: Mapping[int, Decimal] = field(default_factory=dict)


def net_worth_lines(ctx: DbTransactionContext) -> Result[NetWorthLines, BalanceError]:
    """The lines net worth folds: the one definition shared by `net_worth` and
    the history, which folds the same lines at several dates."""
    accounts_res = balance_sheet_accounts(ctx)
    if accounts_res.is_err:
        return Result.err(accounts_res.unwrap_err())
    accounts = accounts_res.unwrap()

    own_lines_res = account_lines_service(ctx, accounts.own.keys())
    if own_lines_res.is_err:
        return Result.err(own_lines_res.unwrap_err())

    receivables_lines_res = account_lines_service(ctx, accounts.people.keys())
    if receivables_lines_res.is_err:
        return Result.err(receivables_lines_res.unwrap_err())

    own_lines = own_lines_res.unwrap()
    receivables_lines = receivables_lines_res.unwrap()
    costs_res = line_costs(ctx, [*own_lines, *receivables_lines])
    if costs_res.is_err:
        return Result.err(costs_res.unwrap_err())

    return Result.ok(NetWorthLines(own_lines, receivables_lines, costs_res.unwrap()))


def net_worth(ctx: DbTransactionContext) -> Result[NetWorthReport, BalanceError]:
    """Net worth at recorded cost (design §9). Income and expense accounts
    are excluded — every entry balances, so including them would always net
    to exactly 0, which would look like a bug rather than a definition error
    (design §9.2). Receivables are the People subtree, unioned in by
    membership rather than selected by account type, so a person account
    still counts even with the default `expense` type `add-account` gives
    it, and nothing is double-counted since the partition is by subtree.
    Factored out of `NetWorth` so `reporting.ValuedNetWorth` can run the same
    partition inside its own transaction."""
    lines_res = net_worth_lines(ctx)
    if lines_res.is_err:
        return Result.err(lines_res.unwrap_err())
    lines = lines_res.unwrap()
    return Result.ok(NetWorthReport(
        own=aggregate_by_unit(lines.own, lines.costs),
        receivables=aggregate_by_unit(lines.receivables, lines.costs),
    ))


class NetWorth(UnitOfWork[NetWorthReport, BalanceError]):
    """Net worth at recorded cost, see `net_worth`. Market valuation is
    `reporting.ValuedNetWorth`; this is `quantity * average_cost`, see
    `UnitBalance.at_cost`."""

    def execute(self) -> Result[NetWorthReport, BalanceError]:
        return self._run(net_worth)
