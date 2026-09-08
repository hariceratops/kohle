from sqlalchemy import select
from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AccountError,
    AccountNotFoundError,
    DuplicateAccountName,
    DuplicateIBAN,
)
from kohle.domain.models import Account, AccountType
from kohle.infrastructure.crud import crud_create, crud_retrieve
from kohle.infrastructure.infra_errors import check_if_unique_constraint_failed
from kohle.infrastructure.transaction_context import DbTransactionContext


@crud_create
def add_account_service(
    ctx: DbTransactionContext,
    name: str,
    account_type: AccountType,
    iban: str | None = None,
    parent_id: int | None = None,
) -> Result[Account, AccountError]:
    def op(session: Session) -> Account:
        account = Account(name=name, type=account_type, iban=iban, parent_id=parent_id)
        session.add(account)
        return account

    return (
        ctx.run(op)
        .map_err(lambda err: (
            DuplicateAccountName(name) if check_if_unique_constraint_failed(err, "accounts.name")
            else DuplicateIBAN(iban) if iban and check_if_unique_constraint_failed(err, "accounts.iban")
            else AccountError(str(err))
        ))
    )


@crud_retrieve
def get_account_by_name_service(ctx: DbTransactionContext, name: str) -> Result[Account, AccountError]:
    def op(session: Session) -> Account | None:
        return session.query(Account).filter(Account.name == name).one_or_none()

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
def get_account_by_iban_service(ctx: DbTransactionContext, iban: str) -> Result[Account, AccountError]:
    def op(session: Session) -> Account | None:
        return session.query(Account).filter(Account.iban == iban).one_or_none()

    return (
        ctx.run(op)
        .map_err(lambda err: AccountError(str(err)))
        .and_then(lambda account:
            Result.ok(account)
            if account is not None
            else Result.err(AccountNotFoundError(iban))
        )
    )


@crud_retrieve
def list_accounts_service(ctx: DbTransactionContext) -> Result[list[Account], AccountError]:
    def op(session: Session) -> list[Account]:
        return session.query(Account).order_by(Account.name).all()

    return ctx.run(op).map_err(lambda err: AccountError(str(err)))


@crud_retrieve
def list_child_accounts_service(ctx: DbTransactionContext, parent_id: int) -> Result[list[Account], AccountError]:
    def op(session: Session) -> list[Account]:
        return session.query(Account).filter(Account.parent_id == parent_id).order_by(Account.name).all()

    return ctx.run(op).map_err(lambda err: AccountError(str(err)))


@crud_retrieve
def account_has_children_service(ctx: DbTransactionContext, account_id: int) -> Result[bool, AccountError]:
    def op(session: Session) -> bool:
        return session.query(Account.id).filter(Account.parent_id == account_id).first() is not None

    return ctx.run(op).map_err(lambda err: AccountError(str(err)))


@crud_retrieve
def descendant_account_ids_service(
    ctx: DbTransactionContext, account_id: int
) -> Result[list[int], AccountError]:
    def op(session: Session) -> list[int]:
        # UNION (not UNION ALL), projecting only Account.id in the recursive
        # term: UNION deduplicates each new row against the accumulated
        # result, so a cycle in parent_id stops producing new rows and the
        # query terminates with the reachable set. Adding a second column
        # such as a depth counter would break this silently — a monotonic
        # column makes every row distinct, so UNION's deduplication never
        # fires, and a corrupt tree would hang instead of returning a wrong
        # answer. Verified against SQLite 3.45 on cyclic parentage.
        seed = select(Account.id).where(Account.id == account_id).cte(recursive=True)
        descendants = seed.union(
            select(Account.id).where(Account.parent_id == seed.c.id)
        )
        return [row[0] for row in session.execute(select(descendants)).all()]

    return ctx.run(op).map_err(lambda err: AccountError(str(err)))
