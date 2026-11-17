from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import uuid4

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    ConversionBetweenCurrencies,
    CurrencyInflowWithoutRate,
    CurrencyLineNotAtPar,
    EmptyEntry,
    JournalError,
    NonPositiveQuantity,
    PostingToNonLeafAccount,
    UnbalancedEntry,
)
from kohle.domain.models import (
    AccountType,
    Classification,
    JournalEntry,
    JournalLine,
    Unit,
    UnitKind,
)
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import (
    account_has_children_service,
    list_accounts_service,
)
from kohle.services.journal_services import (
    Counterparty,
    LineSpec,
    add_journal_entry_service,
)
from kohle.services.unit_services import units_by_id_service

_PRICE_SCALE = Decimal("0.00000001")


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


@dataclass(frozen=True, slots=True)
class Total:
    """The whole euro value of a holding line, stated rather than derived.

    A remittance of 90,000 INR for 1,000 EUR has no terminating per-unit
    rate, so only the total is exact (design §2.1).
    """

    amount: Decimal



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


def post_correction(
    ctx: DbTransactionContext, classification: Classification, to_account_id: int, description: str
) -> Result[JournalEntry, JournalError]:
    """Reverse the line out of final_account_id and post it onto the target.

    The one place a line moves between accounts after import. The original
    counterpart line to mirror is located by proposed_account_id: after a
    first move the original entry still carries its line there, not on the
    final account.
    """
    entry = classification.entry
    original_line = next(line for line in entry.lines if line.account_id == classification.proposed_account_id)
    lines = [
        LineSpec(
            classification.final_account_id, original_line.unit_id, original_line.quantity,
            original_line.unit_price, is_debit=not original_line.is_debit,
        ),
        LineSpec(
            to_account_id, original_line.unit_id, original_line.quantity,
            original_line.unit_price, is_debit=original_line.is_debit,
        ),
    ]
    # Dated the original entry's date, not today: balance and
    # entries-in-period are period queries, and dating the correction
    # today would leave the original period permanently misreported.
    return post_entry(ctx, entry.entry_date, uuid4().hex, description, lines)


def statement_amount(classification: Classification) -> Decimal:
    """The signed amount the import gave the rules: the counterpart line is
    debited exactly when the amount was negative."""
    line = next(line for line in classification.entry.lines if line.account_id == classification.proposed_account_id)
    return -line.value if line.is_debit else line.value


def counterpart_line(classification: Classification) -> JournalLine:
    """The line on proposed_account_id: where the import put the other side."""
    return next(line for line in classification.entry.lines if line.account_id == classification.proposed_account_id)


def statement_line(classification: Classification) -> JournalLine:
    """The other line: the row's own account. For a category rule aimed at the
    importing account both lines sit on one account, and it is that one."""
    counterpart = counterpart_line(classification)
    return next((line for line in classification.entry.lines if line is not counterpart), counterpart)
