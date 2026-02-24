import hashlib
from datetime import date
import pandas as pd
from typing import List
from kohle.infrastructure.uow import UnitOfWork
from kohle.core.result import Result
from kohle.domain.domain_errors import (
    TransactionError, 
    AccountNotFoundError, 
    InvalidDateError, 
    EndDatePrecedesStartDateError,
    QueryTransactionByPeriodError
)
from kohle.services.account_services import get_account_by_name_service
from kohle.services.transactions_services import (
    existing_transactions_service, 
    bulk_insert_transactions_service, 
    query_transactions_by_period_service
)


def import_transaction_statement(uow: UnitOfWork, 
                                 account_name: str, 
                                 df: pd.DataFrame) \
        -> Result[int, AccountNotFoundError | TransactionError]:
    account_id_result = (
        get_account_by_name_service(uow, account_name)
        .map(lambda account: account.id)
    )
    if account_id_result.is_err:
        return Result.err(account_id_result.unwrap_err())

    account_id = account_id_result.unwrap()
    df = (
        df.pipe(lambda d: d.assign(date=pd.to_datetime(d["date"]).dt.date))
          .pipe(lambda d: d.assign(hash=(d[["date", "amount", "description"]].astype(str).agg("|".join, axis=1))))
          .pipe(lambda d: d.assign(hash=d["hash"].apply(lambda x: hashlib.sha256(x.encode()).hexdigest())))
          .pipe(lambda df: df.assign(account_id=account_id))
    )

    existing_transactions_result = existing_transactions_service(uow, df["hash"].to_list())
    if existing_transactions_result.is_err:
        return Result.err(existing_transactions_result.unwrap_err())

    existing_hashes = existing_transactions_result.unwrap()
    new_transactions = df[~df["hash"].isin(existing_hashes)]
    if new_transactions.empty:
        return Result.ok(0)

    records = new_transactions.to_dict("records")
    return bulk_insert_transactions_service(uow, records).map(lambda v: v).map_err(lambda e: e)


def parse_date(input_date: str) -> Result[date, InvalidDateError]:
    try:
        parsed = date.fromisoformat(input_date)
        return Result.ok(parsed)
    except ValueError:
        return Result.err(InvalidDateError(input_date))


def query_transaction_by_period(uow: UnitOfWork,
                                account_name: str,
                                start_date_str: str, 
                                end_date_str: str) \
            -> Result[List[dict], QueryTransactionByPeriodError]:
    account_id_result = (
        get_account_by_name_service(uow, account_name)
        .map(lambda account: account.id)
    )
    if account_id_result.is_err:
        return Result.err(account_id_result.unwrap_err())
    account_id = account_id_result.unwrap()

    start_date_res = parse_date(start_date_str)
    if start_date_res.is_err:
        return Result.err(start_date_res.unwrap_err())
    end_date_res = parse_date(end_date_str)
    if end_date_res.is_err:
        return Result.err(end_date_res.unwrap_err())
    start_date = start_date_res.unwrap()
    end_date = end_date_res.unwrap()
    if start_date >= end_date:
        return Result.err(EndDatePrecedesStartDateError(start_date_str, end_date_str))

    transactions = query_transactions_by_period_service(uow, account_id, start_date, end_date)

    return transactions.map(lambda v: v).map_err(lambda e: e)
    
