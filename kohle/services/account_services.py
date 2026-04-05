from typing import List
from sqlalchemy.orm import Session
from kohle.domain.models import Account
from kohle.infrastructure.crud import crud_create, crud_retrieve
from kohle.infrastructure.uow import DbTransactionContext
from kohle.domain.domain_errors import AccountError, DuplicateAccountName, DuplicateIBAN, AccountNotFoundError
from kohle.infrastructure.infra_errors import check_if_unique_constraint_failed
from kohle.core.result import Result


@crud_create
def add_account_service(ctx: DbTransactionContext, name: str, iban: str) -> Result[Account, AccountError]:
    def op(session: Session) -> Account:
        account = Account(name=name, iban=iban)
        session.add(account)
        return account

    return (
        ctx.run(op)
        .map(lambda v: v)
        .map_err(lambda err: (
            DuplicateAccountName(name) if check_if_unique_constraint_failed(err, "accounts.name")
            else DuplicateIBAN(iban) if check_if_unique_constraint_failed(err, "accounts.iban")
            else AccountError(str(err))
        ))
    )


@crud_retrieve
def get_account_by_name_service(ctx: DbTransactionContext, name: str) -> Result[Account, AccountError]:
    def op(session: Session) -> Account:
        return (session.query(Account).filter(Account.name == name).one_or_none())
    return (
        ctx.run(op)
        .map_err(lambda err: AccountError(str(err)))
        .and_then(lambda account:
            Result.ok(account)
            if account is not None
            else Result.err(AccountNotFoundError(name))
        )
    )


@crud_retrieve
def list_accounts_service(ctx: DbTransactionContext) -> Result[List[Account], AccountError]:
    def op(session: Session) -> List[Account]:
        return session.query(Account).order_by(Account.name).all()
    return (
        ctx.run(op)
        .map_err(lambda err: AccountError(str(err)))
    )
 
