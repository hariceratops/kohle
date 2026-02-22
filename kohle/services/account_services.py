from sqlalchemy.orm import Session
from kohle.domain.models import Account
from kohle.infrastructure.uow import UnitOfWork
from kohle.domain.domain_errors import AccountError, DuplicateAccountName, DuplicateIBAN, AccountNotFoundError
from kohle.infrastructure.infra_errors import check_if_unique_constraint_failed
from kohle.core.result import Result


def add_account_service(uow: UnitOfWork[int], name: str, iban: str) -> Result[int, AccountError]:
    def op(session: Session) -> int:
        account = Account(name=name, iban=iban)
        session.add(account)
        session.flush()  # triggers DB validation
        return account.id

    return (
        uow.run(op)
        .map(lambda v: v)
        .map_err(lambda err: (
            DuplicateAccountName(name) if check_if_unique_constraint_failed(err, "accounts.name")
            else DuplicateIBAN(iban) if check_if_unique_constraint_failed(err, "accounts.iban")
            else AccountError(str(err))
        ))
    )

def get_account_by_name_service(uow: UnitOfWork[Account], name: str) -> Result[Account, AccountError]:
    def op(session: Session) -> Account:
        return (session.query(Account).filter(Account.name == name).one_or_none())
    return (
        uow.run(op)
        .map_err(lambda err: AccountError(str(err)))
        .and_then(lambda account:
            Result.ok(account)
            if account is not None
            else Result.err(AccountNotFoundError(name))
        )
    )

