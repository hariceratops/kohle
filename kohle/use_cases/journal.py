from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import assert_never
from uuid import uuid4

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    BalanceError,
    BaseCurrencyAsCrossUnit,
    DuplicateReferenceInStatement,
    EmptyEntry,
    EndDatePrecedesStartDateError,
    ImportStatementError,
    InvalidDateError,
    JournalError,
    MalformedStatementRow,
    MissingInstrumentAccount,
    NotASecurityUnit,
    PostingToNonLeafAccount,
    QueryJournalByPeriodError,
    RecordEntryError,
    StatementError,
    UnbalancedEntry,
    UnitNotFoundError,
    UnknownInstruments,
)
from kohle.domain.models import AccountType, JournalEntry, JournalLine, Unit, UnitKind
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
from kohle.services.rule_services import list_rules_service
from kohle.services.unit_services import get_unit_by_identifier_service
from kohle.use_cases.rules import compile_rules, match_rule
from kohle.use_cases.units import get_or_create_unit

BASE_CURRENCY = "EUR"
UNCLASSIFIED_EXPENSE = "Unclassified Expense"
PEOPLE_ROOT = "People"
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

    debits = sum((line.value for line in lines if line.is_debit), Decimal(0))
    credits = sum((line.value for line in lines if not line.is_debit), Decimal(0))
    if debits != credits:
        return UnbalancedEntry(debits, credits)

    for line in lines:
        has_children = account_has_children_service(ctx, line.account_id)
        if has_children.is_err:
            return JournalError(str(has_children.unwrap_err()))
        if has_children.unwrap():
            return PostingToNonLeafAccount(line.account_id)

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
class CrossUnitLine:
    """Which side of `record` carries a non-base unit, at what price.

    One value rather than three independent parameters: identifier, price
    and side are mutually dependent — a price without a unit is meaningless,
    a side without a unit is meaningless — and separate `| None` parameters
    would make those invalid combinations representable at the use-case
    boundary, forcing a re-rejection of what the CLI already rejected.
    """

    identifier: str
    price: Decimal
    is_debit: bool


def _cross_unit_lines(
    *,
    holding_account_id: int,
    holding_unit_id: int,
    quantity: Decimal,
    unit_price: Decimal,
    cash_account_id: int,
    cash_unit_id: int,
    into_holding: bool,
) -> list[LineSpec]:
    """Shared by `record` and imported trades so the cost fold sees one
    definition of a trade."""
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

            if cross is None:
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
                    cash_unit_id=base_unit_id,
                    into_holding=cross.is_debit,
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
    unit_price: Decimal
    is_debit: bool


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
                specs.append(
                    LineSpec(
                        account_res.unwrap().id,
                        unit_res.unwrap().id,
                        line.quantity,
                        line.unit_price,
                        line.is_debit,
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
            rules_res = list_rules_service(ctx)
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
                        matched = match_rule(compiled, row.description, counterparty)
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


class _RunningCost:
    """Per-unit accumulator for the moving-average cost fold (design §6.4)."""

    __slots__ = ("basis", "quantity")

    def __init__(self) -> None:
        self.basis = Decimal(0)
        self.quantity = Decimal(0)

    def apply(self, line: JournalLine) -> None:
        if line.is_debit:
            self.basis += line.quantity * line.unit_price
            self.quantity += line.quantity
        else:
            if self.quantity == 0:
                # Net-short in a non-base unit: basis/quantity is undefined.
                # Falling back to the line's own price only keeps the fold
                # from dividing by zero — it is not a claim that this is
                # meaningful accounting, and should not be "improved" into
                # something that looks more principled than it is.
                average = line.unit_price
            else:
                average = self.basis / self.quantity
            self.basis -= line.quantity * average
            self.quantity -= line.quantity

    @property
    def average_cost(self) -> Decimal | None:
        if self.quantity == 0:
            return None
        return self.basis / self.quantity


def aggregate_by_unit(lines: Iterable[JournalLine]) -> list[UnitBalance]:
    """Moving-average cost fold, one accumulator per unit.

    Order-dependent: consumes the caller's ordering as-is and must not sort,
    since `account_lines_service`'s `(entry_date, line id)` order is what
    makes the running average correct (design §6.4).
    """
    running: dict[str, _RunningCost] = {}
    for line in lines:
        identifier = line.unit.identifier
        if identifier not in running:
            running[identifier] = _RunningCost()
        running[identifier].apply(line)
    return [
        UnitBalance(identifier, cost.quantity, cost.average_cost)
        for identifier, cost in running.items()
    ]


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

    return Result.ok(aggregate_by_unit(lines_res.unwrap()))


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
    """`quantity * average_cost`, not `sum(line.value)` — the two coincide
    for a euro-only ledger and diverge the moment a holding is partly sold,
    because the sale's counter-line is priced at the sale price, not the
    cost basis, and so carries the realised gain invisibly (design §9.3).
    `average_cost` is `None` only when `quantity` is 0, so skipping it here
    contributes 0 either way."""
    return sum(
        (b.quantity * b.average_cost for b in balances if b.average_cost is not None),
        Decimal(0),
    )


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


class NetWorth(UnitOfWork[NetWorthReport, BalanceError]):
    """Net worth at recorded cost (design §9). Income and expense accounts
    are excluded — every entry balances, so including them would always net
    to exactly 0, which would look like a bug rather than a definition error
    (design §9.2). Receivables are the People subtree, unioned in by
    membership rather than selected by account type, so a person account
    still counts even with the default `expense` type `add-account` gives
    it, and nothing is double-counted since the partition is by subtree.
    Market valuation is a separate, deferred spec (design §9.4) — this is
    `quantity * average_cost`, see `_at_cost`.
    """

    def execute(self) -> Result[NetWorthReport, BalanceError]:
        def use_case(ctx: DbTransactionContext) -> Result[NetWorthReport, BalanceError]:
            people_res = get_account_by_name_service(ctx, PEOPLE_ROOT)
            if people_res.is_err:
                return Result.err(people_res.unwrap_err())

            people_ids_res = descendant_account_ids_service(ctx, people_res.unwrap().id)
            if people_ids_res.is_err:
                return Result.err(people_ids_res.unwrap_err())
            people_ids = set(people_ids_res.unwrap())

            accounts_res = list_accounts_service(ctx)
            if accounts_res.is_err:
                return Result.err(accounts_res.unwrap_err())
            balance_sheet_ids = {
                a.id for a in accounts_res.unwrap()
                if a.type in (AccountType.asset, AccountType.liability)
            } | people_ids

            own_lines_res = account_lines_service(ctx, balance_sheet_ids - people_ids)
            if own_lines_res.is_err:
                return Result.err(own_lines_res.unwrap_err())

            receivables_lines_res = account_lines_service(ctx, people_ids)
            if receivables_lines_res.is_err:
                return Result.err(receivables_lines_res.unwrap_err())

            return Result.ok(NetWorthReport(
                own=aggregate_by_unit(own_lines_res.unwrap()),
                receivables=aggregate_by_unit(receivables_lines_res.unwrap()),
            ))

        return self._run(use_case)
