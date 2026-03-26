from typing import List
from kohle.core.result import Result
from kohle.infrastructure.uow import UnitOfWork
from kohle.domain.models import Account
from kohle.domain.domain_errors import AccountError, EmptyAccountName, EmptyIBAN
from kohle.services.account_services import add_account_service, list_accounts_service


def add_account(uow: UnitOfWork, account_name: str, iban: str) -> Result[Account, AccountError]:
    account_name = account_name.strip()
    if not account_name:
        return Result.err(EmptyAccountName())
    if not iban:
        return Result.err(EmptyIBAN())
    return add_account_service(uow, account_name, iban)


def list_accounts(uow: UnitOfWork) -> Result[List[Account], AccountError]:
    return list_accounts_service(uow)

