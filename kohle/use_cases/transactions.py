import hashlib
import pandas as pd
from kohle.infrastructure.uow import UnitOfWork
from kohle.core.result import Result
from kohle.db.connection import session_local
from kohle.domain.domain_errors import TransactionError, AccountNotFoundError
from kohle.services.account_services import get_account_by_name_service
from kohle.services.transactions_services import existing_transactions_service, bulk_insert_transactions_service


def import_transaction_statement(account_name: str, df: pd.DataFrame) -> Result[int, AccountNotFoundError | TransactionError]:
    with UnitOfWork(session_local()) as uow:
        account_id_result = (
            get_account_by_name_service(uow, account_name)
            .map(lambda account: account.id)
        )
        if account_id_result.is_err:
            return account_id_result

        account_id = account_id_result.unwrap()
        df = (
            df.pipe(lambda d: d.assign(date=pd.to_datetime(d["date"]).dt.date))
              .pipe(lambda d: d.assign(hash=(d[["date", "amount", "description"]].astype(str).agg("|".join, axis=1))))
              .pipe(lambda d: d.assign(hash=d["hash"].apply(lambda x: hashlib.sha256(x.encode()).hexdigest())))
              .pipe(lambda df: df.assign(account_id=account_id))
        )

        existing_transactions_result = existing_transactions_service(uow, df["hash"].to_list())
        if existing_transactions_result.is_err:
            return existing_transactions_result

        existing_hashes = existing_transactions_result.unwrap()
        new_transactions = df[~df["hash"].isin(existing_hashes)]
        if new_transactions.empty:
            return Result.ok(0)

        records = new_transactions.to_dict("records")
        return bulk_insert_transactions_service(uow, records).map(lambda v: v).map_err(lambda e: e)

