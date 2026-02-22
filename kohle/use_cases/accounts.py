from kohle.core.result import Result
from kohle.db.connection import session_local
from kohle.infrastructure.uow import UnitOfWork
from kohle.domain.domain_errors import AccountError, EmptyAccountName, EmptyIBAN
from kohle.services.account_services import add_account_service


def add_account(account_name: str, iban: str) -> Result[int, AccountError]:
    account_name = account_name.strip()
    if not account_name:
        return Result.err(EmptyAccountName())
    if not iban:
        return Result.err(EmptyIBAN())
    with UnitOfWork(session_local()) as uow:
        return add_account_service(uow, account_name, iban)

