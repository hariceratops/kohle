import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_float_dtype,
    is_integer_dtype,
    is_string_dtype,
)

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    BalanceError,
    DataframeColumnTypeMismatch,
    DataframeMissingColumn,
    DataframeValidationError,
    EmptyEntry,
    EndDatePrecedesStartDateError,
    ImportStatementError,
    InvalidDateError,
    JournalError,
    PostingToNonLeafAccount,
    QueryJournalByPeriodError,
    RecordEntryError,
    UnbalancedEntry,
)
from kohle.domain.models import AccountType, JournalEntry, JournalLine, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    account_has_children_service,
    add_account_service,
    descendant_account_ids_service,
    get_account_by_name_service,
)
from kohle.services.journal_services import (
    LineSpec,
    account_lines_service,
    add_journal_entry_service,
    existing_references_service,
    query_lines_by_period_service,
)
from kohle.use_cases.units import get_or_create_unit

BASE_CURRENCY = "EUR"
UNCLASSIFIED_EXPENSE = "Unclassified Expense"
UNCLASSIFIED_INCOME = "Unclassified Income"


def validate_df_schema(df: pd.DataFrame, expected_schema: dict[str, str]) -> DataframeValidationError | None:
    missing = [col for col in expected_schema if col not in df.columns]
    if missing:
        return DataframeMissingColumn(missing)

    mismatches: dict[str, str] = {}
    for col, expected_type in expected_schema.items():
        series = df[col]
        valid = (
            (expected_type == "int" and is_integer_dtype(series))
            or (expected_type == "float" and is_float_dtype(series))
            or (expected_type == "string" and is_string_dtype(series))
            or (expected_type == "datetime" and is_datetime64_any_dtype(series))
            or (expected_type == "bool" and is_bool_dtype(series))
        )
        if not valid:
            mismatches[col] = str(series.dtype)

    if mismatches:
        return DataframeColumnTypeMismatch(mismatches)

    return None


def parse_date(input_date: str) -> Result[date, InvalidDateError]:
    try:
        return Result.ok(date.fromisoformat(input_date))
    except ValueError:
        return Result.err(InvalidDateError(input_date))


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
) -> Result[JournalEntry, JournalError]:
    invalid = validate_lines(ctx, lines)
    if invalid:
        return Result.err(invalid)
    return add_journal_entry_service(ctx, entry_date, reference, description, lines)


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


class RecordSimpleEntry(UnitOfWork[JournalEntry, RecordEntryError]):
    """The `record` CLI command's use case: a two-line, base-currency entry.

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
    ) -> Result[JournalEntry, RecordEntryError]:
        def use_case(ctx: DbTransactionContext) -> Result[JournalEntry, RecordEntryError]:
            from_res = get_account_by_name_service(ctx, from_account)
            if from_res.is_err:
                return Result.err(from_res.unwrap_err())
            to_res = get_account_by_name_service(ctx, to_account)
            if to_res.is_err:
                return Result.err(to_res.unwrap_err())

            unit_res = get_or_create_unit(ctx, BASE_CURRENCY, "Euro", UnitKind.currency)
            if unit_res.is_err:
                return Result.err(unit_res.unwrap_err())

            from_id = from_res.unwrap().id
            to_id = to_res.unwrap().id
            unit_id = unit_res.unwrap().id

            lines = [
                LineSpec(to_id, unit_id, quantity, Decimal(1), is_debit=True),
                LineSpec(from_id, unit_id, quantity, Decimal(1), is_debit=False),
            ]
            entry_res = post_entry(ctx, entry_date, uuid4().hex, description, lines)
            if entry_res.is_err:
                return Result.err(entry_res.unwrap_err())
            return Result.ok(entry_res.unwrap())

        return self._run(use_case)


class ImportStatement(UnitOfWork[int, ImportStatementError]):
    """Statement rows become balanced entries against an unclassified bucket.
    Choosing a better counterpart account is the classifier's job."""

    def execute(self, account_name: str, df: pd.DataFrame) -> Result[int, ImportStatementError]:
        def use_case(ctx: DbTransactionContext) -> Result[int, ImportStatementError]:
            schema = {
                "description": "string",
                "amount": "float",
                "date": "datetime",
                "iban": "string",
            }
            invalid_df = validate_df_schema(df, schema)
            if invalid_df:
                return Result.err(invalid_df)

            account_res = get_account_by_name_service(ctx, account_name)
            if account_res.is_err:
                return Result.err(account_res.unwrap_err())
            account = account_res.unwrap()

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

            # The account is part of the reference: the same row on two
            # different statements is two different facts, and without it the
            # second import is silently swallowed as a duplicate.
            rows = (
                df.pipe(lambda d: d.assign(date=pd.to_datetime(d["date"]).dt.date))
                  .pipe(lambda d: d.assign(
                      reference=d[["date", "amount", "description"]].astype(str).agg("|".join, axis=1)
                  ))
                  .pipe(lambda d: d.assign(
                      reference=d["reference"].apply(
                          lambda x: hashlib.sha256(f"{account.id}|{x}".encode()).hexdigest()
                      )
                  ))
            )

            existing_res = existing_references_service(ctx, rows["reference"].to_list())
            if existing_res.is_err:
                return Result.err(existing_res.unwrap_err())
            existing = existing_res.unwrap()

            new_rows = rows[~rows["reference"].isin(existing)]
            if new_rows.empty:
                return Result.ok(0)

            imported = 0
            for row in new_rows.to_dict("records"):
                amount = Decimal(str(row["amount"]))
                magnitude = abs(amount)
                counterpart_id = expense_id if amount < 0 else income_id
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
                invalid = validate_lines(ctx, lines)
                if invalid:
                    return Result.err(invalid)

                entry_res = add_journal_entry_service(
                    ctx, row["date"], row["reference"], row["description"], lines
                )
                if entry_res.is_err:
                    return Result.err(entry_res.unwrap_err())
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


def _aggregate_by_unit(lines: Iterable[JournalLine]) -> list[UnitBalance]:
    quantities: dict[str, Decimal] = {}
    for line in lines:
        signed = line.quantity if line.is_debit else -line.quantity
        quantities[line.unit.identifier] = quantities.get(line.unit.identifier, Decimal(0)) + signed
    return [UnitBalance(identifier, quantity) for identifier, quantity in quantities.items()]


class QueryAccountBalance(UnitOfWork[list[UnitBalance], BalanceError]):
    def execute(self, account_name: str) -> Result[list[UnitBalance], BalanceError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[UnitBalance], BalanceError]:
            account_res = get_account_by_name_service(ctx, account_name)
            if account_res.is_err:
                return Result.err(account_res.unwrap_err())

            descendants_res = descendant_account_ids_service(ctx, account_res.unwrap().id)
            if descendants_res.is_err:
                return Result.err(descendants_res.unwrap_err())

            lines_res = account_lines_service(ctx, descendants_res.unwrap())
            if lines_res.is_err:
                return Result.err(lines_res.unwrap_err())

            return Result.ok(_aggregate_by_unit(lines_res.unwrap()))

        return self._run(use_case)
