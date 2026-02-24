from typing import List
from kohle.core.result import Result
from kohle.infrastructure.uow import UnitOfWork
from kohle.domain.domain_errors import AccountError, EmptyAccountName, EmptyIBAN
from kohle.services.account_services import add_account_service, list_accounts_service


def add_account(uow: UnitOfWork, account_name: str, iban: str) -> Result[int, AccountError]:
    account_name = account_name.strip()
    if not account_name:
        return Result.err(EmptyAccountName())
    if not iban:
        return Result.err(EmptyIBAN())
    return add_account_service(uow, account_name, iban)


def list_accounts(uow: UnitOfWork) -> Result[List[dict], AccountError]:
    res = list_accounts_service(uow)
    if res.is_err:
        return Result.err(res.unwrap_err())
    accounts = [{"id": a.id, "name": a.name, "iban": a.iban} for a in res.unwrap()]
    return Result.ok(accounts)

