"""Spending caps: the account partition and the cap use cases (design §5, §8).
Reads no prices, so the price guard covers it like journal.py."""

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AccountError,
    AccountNotFoundError,
    BudgetError,
    CapError,
    CapWriteError,
    InvalidCapAmount,
    UncappableAccount,
)
from kohle.domain.models import Account, AccountType, CapEntry, JournalLine
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    descendant_account_ids_service,
    get_account_by_name_service,
    list_accounts_service,
)
from kohle.services.cap_services import list_cap_entries_service, put_cap_entry_service
from kohle.services.journal_services import account_lines_service
from kohle.services.state_services import list_state_entries_service
from kohle.use_cases.bundesland import state_lookup
from kohle.use_cases.journal import PEOPLE_ROOT, UNCLASSIFIED_EXPENSE
from kohle.use_cases.recurrence import (
    Recurrence,
    next_occurrence,
    parse_recurrence,
    render_recurrence,
)


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


@dataclass(frozen=True, slots=True)
class Cap:
    amount: Decimal
    recurrence: Recurrence


@dataclass(frozen=True, slots=True)
class CapChange:
    """One entry of an account's cap history, with its rule parsed."""

    effective_from: date
    cap: Cap


@dataclass(frozen=True, slots=True)
class Period:
    start: date
    end: date
    cap: Decimal
    short: bool

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def cap_periods(history: Sequence[CapChange], state_on: Callable[[date], str], through: date) -> list[Period]:
    """One account's periods that start on or before `through`, oldest first.
    An entry cuts the running period on the day before it, unless it repeats
    the entry before it."""
    entries = [c for i, c in enumerate(history) if i == 0 or c.cap != history[i - 1].cap]
    periods: list[Period] = []
    for i, entry in enumerate(entries):
        span_end = entries[i + 1].effective_from - timedelta(days=1) if i + 1 < len(entries) else None
        rule = entry.cap.recurrence
        start = entry.effective_from
        while start <= through and (span_end is None or start <= span_end):
            natural_end = next_occurrence(rule, start, state_on) - timedelta(days=1)
            end = natural_end if span_end is None else min(natural_end, span_end)
            starts_on_occurrence = next_occurrence(rule, start - timedelta(days=1), state_on) == start
            periods.append(Period(start, end, entry.cap.amount, short=not starts_on_occurrence or end != natural_end))
            start = end + timedelta(days=1)
    return periods


def net_spent(lines: Iterable[JournalLine], first: date, last: date) -> Decimal:
    """Debits minus credits at each line's recorded value, for lines dated in [first, last]."""
    return sum(
        (line.value if line.is_debit else -line.value for line in lines if first <= line.entry.entry_date <= last),
        Decimal(0),
    )


@dataclass(frozen=True, slots=True)
class CappedAccount:
    name: str
    history: list[CapChange]  # oldest first
    covers: frozenset[int]


@dataclass(frozen=True, slots=True)
class BudgetRow:
    account: str
    period: Period
    spent: Decimal
    day: int | None  # today's day number in the period, counting from 1, if it contains today

    @property
    def over(self) -> Decimal:
        return self.spent - self.period.cap

    @property
    def is_over(self) -> bool:
        return self.spent > self.period.cap


@dataclass(frozen=True, slots=True)
class BudgetReport:
    rows: list[BudgetRow]


def period_rows(
    capped: Sequence[CappedAccount],
    lines: Sequence[JournalLine],
    state_on: Callable[[date], str],
    start: date,
    end: date,
    today: date,
) -> list[BudgetRow]:
    rows: list[BudgetRow] = []
    for account in capped:
        own = [line for line in lines if line.account_id in account.covers]
        for period in cap_periods(account.history, state_on, min(end, today)):
            if period.end < start:
                continue
            day = (today - period.start).days + 1 if period.start <= today <= period.end else None
            rows.append(BudgetRow(account.name, period, net_spent(own, period.start, period.end), day))
    return rows


class QueryBudget(UnitOfWork[BudgetReport, BudgetError]):
    def execute(self, start: date, end: date, today: date) -> Result[BudgetReport, BudgetError]:
        def use_case(ctx: DbTransactionContext) -> Result[BudgetReport, BudgetError]:
            accounts_res = budget_accounts(ctx)
            if accounts_res.is_err:
                return Result.err(accounts_res.unwrap_err())
            by_id = {a.id: a.name for a in accounts_res.unwrap().accounts.values()}

            entries_res = list_cap_entries_service(ctx)
            if entries_res.is_err:
                return Result.err(entries_res.unwrap_err())
            histories: dict[int, list[CapChange]] = defaultdict(list)
            for entry in entries_res.unwrap():
                if entry.amount is None or entry.rule is None:
                    continue
                parsed = parse_recurrence(entry.rule)
                if parsed.is_err:
                    return Result.err(parsed.unwrap_err())
                histories[entry.account_id].append(
                    CapChange(entry.effective_from, Cap(entry.amount, parsed.unwrap()))
                )

            capped: list[CappedAccount] = []
            for account_id in sorted(histories, key=lambda i: by_id[i]):
                ids_res = descendant_account_ids_service(ctx, account_id)
                if ids_res.is_err:
                    return Result.err(ids_res.unwrap_err())
                capped.append(CappedAccount(by_id[account_id], histories[account_id], frozenset(ids_res.unwrap())))

            states_res = list_state_entries_service(ctx)
            if states_res.is_err:
                return Result.err(states_res.unwrap_err())
            lookup_res = state_lookup(states_res.unwrap())
            if lookup_res.is_err:
                return Result.err(lookup_res.unwrap_err())

            covered = set().union(*(c.covers for c in capped))
            lines_res = account_lines_service(ctx, covered)
            if lines_res.is_err:
                return Result.err(lines_res.unwrap_err())

            rows = period_rows(capped, lines_res.unwrap(), lookup_res.unwrap(), start, end, today)
            return Result.ok(BudgetReport(rows))

        return self._run(use_case)
