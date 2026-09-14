"""Layer 3 — use-case tests against the `session` fixture.

`NetWorth` (issue 024), living in `kohle/use_cases/journal.py` beside
`QueryAccountBalance` (design §9.1). The trap this file exists to guard is
§9.3: net worth must be `quantity x average_cost`, not `sum(line.value)` —
the two formulas coincide for a euro-only ledger and diverge the moment a
holding is partly sold, which is exactly why the divergence needs its own
test rather than trusting the cash-envelope scenario to catch it.

Requires the `people_root` fixture (conftest.py).
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from kohle.domain.models import AccountType, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import add_account_service
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.unit_services import add_unit_service
from kohle.use_cases.journal import NetWorth


def test_net_worth_includes_people_and_excludes_flow_accounts(session: Session, people_root) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
    groceries = add_account_service(ctx, "Groceries", AccountType.expense).unwrap()
    alice = add_account_service(ctx, "Alice", AccountType.asset, None, people_root.id).unwrap()
    bob = add_account_service(ctx, "Bob", AccountType.asset, None, people_root.id).unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()

    # 1000 into checking from an income account — excluded from net worth
    # either way, but exercised so its absence isn't an accident of no data.
    income = add_account_service(ctx, "Salary", AccountType.income).unwrap()
    add_journal_entry_service(
        ctx, date(2026, 3, 1), "ref-salary", "Salary",
        [
            LineSpec(checking.id, eur.id, Decimal(1000), Decimal(1), is_debit=True),
            LineSpec(income.id, eur.id, Decimal(1000), Decimal(1), is_debit=False),
        ],
    )
    # 80 spent on groceries — an expense account, also excluded.
    add_journal_entry_service(
        ctx, date(2026, 3, 2), "ref-groceries", "Groceries",
        [
            LineSpec(groceries.id, eur.id, Decimal(80), Decimal(1), is_debit=True),
            LineSpec(checking.id, eur.id, Decimal(80), Decimal(1), is_debit=False),
        ],
    )
    # Alice owes the user 48 (positive person balance) — a receivable.
    add_journal_entry_service(
        ctx, date(2026, 3, 3), "ref-dinner", "Dinner paid for Alice",
        [
            LineSpec(alice.id, eur.id, Decimal(48), Decimal(1), is_debit=True),
            LineSpec(checking.id, eur.id, Decimal(48), Decimal(1), is_debit=False),
        ],
    )
    # The user owes Bob 20 (negative person balance) — a liability.
    add_journal_entry_service(
        ctx, date(2026, 3, 4), "ref-bob", "Bob covered a taxi",
        [
            LineSpec(checking.id, eur.id, Decimal(20), Decimal(1), is_debit=True),
            LineSpec(bob.id, eur.id, Decimal(20), Decimal(1), is_debit=False),
        ],
    )
    session.commit()

    result = NetWorth(session).execute()
    assert result.is_ok
    report = result.unwrap()

    # Checking: +1000 -80 -48 +20 = 892 (paying Alice's dinner and Bob's
    # taxi both leave checking), and it's the only own account.
    assert report.own_at_cost == Decimal(892)
    # Alice +48, Bob -20 -> 28. A positive person balance raises net worth,
    # a negative one lowers it, and neither income nor expense contribute.
    assert report.receivables_at_cost == Decimal(28)
    assert report.net_worth_at_cost == Decimal(920)


def test_net_worth_uses_average_cost_not_sum_of_line_values(session: Session, people_root) -> None:
    # Buy 10 @ 100, sell 5 @ 130, starting from zero cash.
    #
    # Signed line values: Broker 1000 - 650 = 350, Checking -1000 + 650 =
    # -350. Total 0 -- the ledger would claim nothing happened.
    #
    # Moving-average fold: Broker quantity 5, average cost 100 -> 500 at
    # cost; Checking -350. Total 150 -- the realised gain (design §9.3).
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
    broker = add_account_service(ctx, "Broker", AccountType.asset, "DE2").unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    share = add_unit_service(ctx, "IE00B4L5Y983", "Core MSCI World", UnitKind.security).unwrap()

    add_journal_entry_service(
        ctx, date(2026, 3, 1), "buy-1", "Bought 10 shares",
        [
            LineSpec(broker.id, share.id, Decimal(10), Decimal(100), is_debit=True),
            LineSpec(checking.id, eur.id, Decimal(1000), Decimal(1), is_debit=False),
        ],
    )
    add_journal_entry_service(
        ctx, date(2026, 3, 2), "sell-1", "Sold 5 shares",
        [
            LineSpec(checking.id, eur.id, Decimal(650), Decimal(1), is_debit=True),
            LineSpec(broker.id, share.id, Decimal(5), Decimal(130), is_debit=False),
        ],
    )
    session.commit()

    result = NetWorth(session).execute()
    assert result.is_ok
    report = result.unwrap()

    assert report.receivables_at_cost == Decimal(0)
    assert report.net_worth_at_cost == Decimal(150)
