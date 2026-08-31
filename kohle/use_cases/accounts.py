from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AccountError,
    EmptyAccountName,
    ParentAccountNotFound,
)
from kohle.domain.models import Account, AccountType
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    add_account_service,
    get_account_by_name_service,
    list_accounts_service,
    list_child_accounts_service,
)


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
