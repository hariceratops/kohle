import hashlib
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

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
    UnbalancedEntry,
)
from kohle.domain.models import AccountType, JournalEntry, JournalLine, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    account_has_children_service,
    add_account_service,
    get_account_by_name_service,
)
from kohle.services.journal_services import (
    LineSpec,
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


class RecordJournalEntry(UnitOfWork[JournalEntry, JournalError]):
    def execute(
        self,
        entry_date: date,
        reference: str,
        description: str,
        lines: Iterable[LineSpec],
    ) -> Result[JournalEntry, JournalError]:
        def use_case(ctx: DbTransactionContext) -> Result[JournalEntry, JournalError]:
            line_list = list(lines)
            invalid = validate_lines(ctx, line_list)
            if invalid:
                return Result.err(invalid)
            return add_journal_entry_service(ctx, entry_date, reference, description, line_list)

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
