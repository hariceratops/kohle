from dataclasses import dataclass

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AccountError,
    EmptyAccountName,
    ParentAccountNotFound,
    ParentHasPostings,
)
from kohle.domain.models import Account, AccountType
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    account_has_postings_service,
    add_account_service,
    descendant_account_ids_service,
    get_account_by_name_service,
    list_accounts_service,
    list_child_accounts_service,
)

PEOPLE_ROOT = "People"


class AddAccount(UnitOfWork[Account, AccountError]):
    def execute(
        self,
        account_name: str,
        account_type: AccountType,
        iban: str | None = None,
        parent_name: str | None = None,
    ) -> Result[Account, AccountError]:
        def use_case(ctx: DbTransactionContext) -> Result[Account, AccountError]:
            name = account_name.strip()
            if not name:
                return Result.err(EmptyAccountName())

            parent_id = None
            if parent_name:
                parent_res = get_account_by_name_service(ctx, parent_name)
                if parent_res.is_err:
                    return Result.err(ParentAccountNotFound(parent_name))
                parent_id = parent_res.unwrap().id
                has_postings = account_has_postings_service(ctx, parent_id)
                if has_postings.is_err:
                    return Result.err(has_postings.unwrap_err())
                if has_postings.unwrap():
                    return Result.err(ParentHasPostings(parent_name))

            return add_account_service(ctx, name, account_type, iban or None, parent_id)

        return self._run(use_case)


class ListAccount(UnitOfWork[list[Account], AccountError]):
    def execute(self) -> Result[list[Account], AccountError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[Account], AccountError]:
            return list_accounts_service(ctx)

        return self._run(use_case)


class ListChildAccounts(UnitOfWork[list[Account], AccountError]):
    def execute(self, parent_name: str) -> Result[list[Account], AccountError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[Account], AccountError]:
            return (
                get_account_by_name_service(ctx, parent_name)
                .and_then(lambda parent: list_child_accounts_service(ctx, parent.id))
            )

        return self._run(use_case)


@dataclass(frozen=True, slots=True)
class BalanceSheetAccounts:
    own: dict[int, str]
    people: dict[int, str]


def balance_sheet_accounts(ctx: DbTransactionContext) -> Result[BalanceSheetAccounts, AccountError]:
    """The net-worth partition, account id to name: asset and liability
    accounts outside the People subtree (`own`), and the People subtree of any
    type (`people`). Shared so "own account" has one definition."""
    people_res = get_account_by_name_service(ctx, PEOPLE_ROOT)
    if people_res.is_err:
        return Result.err(people_res.unwrap_err())

    people_ids_res = descendant_account_ids_service(ctx, people_res.unwrap().id)
    if people_ids_res.is_err:
        return Result.err(people_ids_res.unwrap_err())
    people_ids = set(people_ids_res.unwrap())

    accounts_res = list_accounts_service(ctx)
    if accounts_res.is_err:
        return Result.err(accounts_res.unwrap_err())
    accounts = accounts_res.unwrap()
    return Result.ok(BalanceSheetAccounts(
        own={
            a.id: a.name for a in accounts
            if a.type in (AccountType.asset, AccountType.liability) and a.id not in people_ids
        },
        people={a.id: a.name for a in accounts if a.id in people_ids},
    ))
