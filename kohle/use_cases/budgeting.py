"""Spending caps: the account partition and the cap use cases (design §5, §8).
Reads no prices, so the price guard covers it like journal.py."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AccountError,
    AccountNotFoundError,
    CapError,
    CapWriteError,
    InvalidCapAmount,
    UncappableAccount,
)
from kohle.domain.models import Account, AccountType, CapEntry
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    descendant_account_ids_service,
    get_account_by_name_service,
    list_accounts_service,
)
from kohle.services.cap_services import list_cap_entries_service, put_cap_entry_service
from kohle.use_cases.journal import PEOPLE_ROOT, UNCLASSIFIED_EXPENSE
from kohle.use_cases.recurrence import parse_recurrence, render_recurrence


@dataclass(frozen=True, slots=True)
class BudgetAccounts:
    accounts: dict[str, Account]
    people: frozenset[int]
    unclassified: frozenset[int]  # empty before the first import creates the account

    def cappable(self) -> list[Account]:
        """Expense accounts outside both subtrees, by name: what set-cap
        accepts, and the accounts whose lines the uncapped row counts."""
        return [
            a for _, a in sorted(self.accounts.items())
            if a.type == AccountType.expense and a.id not in self.people and a.id not in self.unclassified
        ]


def _subtree(ctx: DbTransactionContext, root: str) -> Result[frozenset[int], AccountError]:
    root_res = get_account_by_name_service(ctx, root)
    if root_res.is_err:
        return Result.err(root_res.unwrap_err())
    ids_res = descendant_account_ids_service(ctx, root_res.unwrap().id)
    if ids_res.is_err:
        return Result.err(ids_res.unwrap_err())
    return Result.ok(frozenset(ids_res.unwrap()))


def budget_accounts(ctx: DbTransactionContext) -> Result[BudgetAccounts, AccountError]:
    accounts_res = list_accounts_service(ctx)
    if accounts_res.is_err:
        return Result.err(accounts_res.unwrap_err())

    people_res = _subtree(ctx, PEOPLE_ROOT)
    if people_res.is_err:
        return Result.err(people_res.unwrap_err())

    unclassified_res = _subtree(ctx, UNCLASSIFIED_EXPENSE)
    if unclassified_res.is_err:
        if not isinstance(unclassified_res.unwrap_err(), AccountNotFoundError):
            return Result.err(unclassified_res.unwrap_err())
        unclassified: frozenset[int] = frozenset()
    else:
        unclassified = unclassified_res.unwrap()

    return Result.ok(BudgetAccounts(
        accounts={a.name: a for a in accounts_res.unwrap()},
        people=people_res.unwrap(),
        unclassified=unclassified,
    ))


def check_cappable(accounts: BudgetAccounts, name: str) -> Result[Account, UncappableAccount]:
    """Checks in this order so each message names the real problem: person
    accounts are usually of type expense, and Unclassified Expense always is."""
    def refuse(problem: str) -> Result[Account, UncappableAccount]:
        return Result.err(UncappableAccount(name, problem, [a.name for a in accounts.cappable()]))

    account = accounts.accounts.get(name)
    if account is None:
        return refuse("no such account")
    if account.id in accounts.unclassified:
        return refuse("it has its own row in budget")
    if account.id in accounts.people:
        return refuse("it is a person under People")
    if account.type != AccountType.expense:
        return refuse(f"it is an {account.type.value} account")
    return Result.ok(account)


class SetCap(UnitOfWork[CapEntry, CapWriteError]):
    def execute(
        self, account_name: str, amount: Decimal, rule: str, effective_from: date
    ) -> Result[CapEntry, CapWriteError]:
        if not amount.is_finite() or amount < 0:
            return Result.err(InvalidCapAmount(amount))
        parsed = parse_recurrence(rule)
        if parsed.is_err:
            return Result.err(parsed.unwrap_err())
        canonical = render_recurrence(parsed.unwrap())

        def use_case(ctx: DbTransactionContext) -> Result[CapEntry, CapWriteError]:
            accounts_res = budget_accounts(ctx)
            if accounts_res.is_err:
                return Result.err(accounts_res.unwrap_err())
            account_res = check_cappable(accounts_res.unwrap(), account_name)
            if account_res.is_err:
                return Result.err(account_res.unwrap_err())
            return put_cap_entry_service(ctx, account_res.unwrap().id, effective_from, amount, canonical)

        return self._run(use_case)


class ListCaps(UnitOfWork[list[CapEntry], CapError]):
    def execute(self) -> Result[list[CapEntry], CapError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[CapEntry], CapError]:
            return list_cap_entries_service(ctx)

        return self._run(use_case)
