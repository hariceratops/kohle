from typing import List, Callable
from kohle.core.result import Result
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.domain.models import Account
from kohle.domain.domain_errors import AccountError, EmptyAccountName, EmptyIBAN
from kohle.services.account_services import add_account_service, list_accounts_service


class AddAccount(UnitOfWork[Account, AccountError]):
    def execute(self, account_name: str, iban: str) -> Result[Account, AccountError]:
        def use_case(ctx: DbTransactionContext) -> Result[Account, AccountError]:
            name = account_name.strip()
            if not name:
                return Result.err(EmptyAccountName())
            if not iban:
                return Result.err(EmptyIBAN())
            return add_account_service(ctx, name, iban)
        return self._run(use_case)


class ListAccount(UnitOfWork[List[Account], AccountError]):
    def execute(self) -> Result[List[Account], AccountError]:
        def use_case(ctx: DbTransactionContext) -> Result[List[Account], AccountError]:
            return list_accounts_service(ctx)
        return self._run(use_case)

