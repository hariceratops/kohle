"""Layer 2 — service tests against the `session` fixture.

The balance aggregation query (issues 002, 003).

Eager loading matters here: `UnitOfWork` closes its session before the caller
reads the result, so anything the CLI displays has to be loaded in the
service. This has already bitten once — `query_lines_by_period_service`
needs joinedload on entry and unit for exactly this reason.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from kohle.domain.models import AccountType, UnitKind
from kohle.services.journal_services import LineSpec
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import (
    QueryAccountBalance,
    RecordJournalEntry,
    RecordSimpleEntry,
)
from kohle.use_cases.units import AddUnit


def _accounts_and_units(session: Session) -> tuple[int, int, int]:
    checking = AddAccount(session).execute("Checking", AccountType.asset, "DE1").unwrap()
    groceries = AddAccount(session).execute("Groceries", AccountType.expense).unwrap()
    eur = AddUnit(session).execute("EUR", "Euro", UnitKind.currency).unwrap()
    return checking.id, groceries.id, eur.id


def test_quantity_is_debits_minus_credits(session: Session) -> None:
    checking_id, groceries_id, eur_id = _accounts_and_units(session)
    RecordJournalEntry(session).execute(
        date(2026, 3, 1), "ref-1", "Aldi",
        [
            LineSpec(groceries_id, eur_id, Decimal(80), Decimal(1), is_debit=True),
            LineSpec(checking_id, eur_id, Decimal(80), Decimal(1), is_debit=False),
        ],
    )

    result = QueryAccountBalance(session).execute("Groceries")

    assert result.is_ok
    balances = result.unwrap()
    assert len(balances) == 1
    assert balances[0].unit_identifier == "EUR"
    assert balances[0].quantity == Decimal(80)


def test_one_row_per_unit_never_combined(session: Session) -> None:
    checking_id, _, eur_id = _accounts_and_units(session)
    broker = AddAccount(session).execute("Broker", AccountType.asset, "DE2").unwrap()
    share = AddUnit(session).execute("IE00B4L5Y983", "Core MSCI World", UnitKind.security).unwrap()

    RecordJournalEntry(session).execute(
        date(2026, 3, 1), "buy-1", "Bought 10 shares",
        [
            LineSpec(broker.id, share.id, Decimal(10), Decimal(100), is_debit=True),
            LineSpec(checking_id, eur_id, Decimal(1000), Decimal(1), is_debit=False),
        ],
    )
    RecordJournalEntry(session).execute(
        date(2026, 3, 2), "buy-2", "Deposit EUR",
        [
            LineSpec(broker.id, eur_id, Decimal(50), Decimal(1), is_debit=True),
            LineSpec(checking_id, eur_id, Decimal(50), Decimal(1), is_debit=False),
        ],
    )

    result = QueryAccountBalance(session).execute("Broker")

    assert result.is_ok
    balances = {b.unit_identifier: b.quantity for b in result.unwrap()}
    assert balances == {"IE00B4L5Y983": Decimal(10), "EUR": Decimal(50)}


def test_account_with_no_lines_returns_empty_result(session: Session) -> None:
    _accounts_and_units(session)

    result = QueryAccountBalance(session).execute("Groceries")

    assert result.is_ok
    assert result.unwrap() == []


def test_unit_readable_after_session_closes(session: Session) -> None:
    checking_id, groceries_id, eur_id = _accounts_and_units(session)
    RecordJournalEntry(session).execute(
        date(2026, 3, 1), "ref-1", "Aldi",
        [
            LineSpec(groceries_id, eur_id, Decimal(80), Decimal(1), is_debit=True),
            LineSpec(checking_id, eur_id, Decimal(80), Decimal(1), is_debit=False),
        ],
    )

    result = QueryAccountBalance(session).execute("Groceries")

    assert result.is_ok
    # QueryAccountBalance's UnitOfWork closes the session inside execute();
    # reading unit_identifier here only works because the use case aggregated
    # into UnitBalance before returning, not because an ORM object survived.
    assert result.unwrap()[0].unit_identifier == "EUR"

def test_rollup_aggregates_every_descendant_not_only_direct_children(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1").unwrap()
    AddAccount(session).execute("Cash", AccountType.asset).unwrap()
    AddAccount(session).execute("Unallocated", AccountType.asset, None, "Cash").unwrap()
    AddAccount(session).execute("Envelopes", AccountType.asset, None, "Cash").unwrap()
    AddAccount(session).execute("Groceries", AccountType.asset, None, "Envelopes").unwrap()
    AddAccount(session).execute("Eating out", AccountType.asset, None, "Envelopes").unwrap()

    # Withdraw into Unallocated, a direct child of Cash.
    RecordSimpleEntry(session).execute(
        date(2026, 3, 1), "Withdraw", Decimal(200), "Checking", "Unallocated"
    ).unwrap()
    # Allocate into Groceries, a grandchild of Cash via Envelopes.
    RecordSimpleEntry(session).execute(
        date(2026, 3, 2), "Allocate groceries", Decimal(80), "Unallocated", "Groceries"
    ).unwrap()
    # Allocate into Eating out, another grandchild.
    RecordSimpleEntry(session).execute(
        date(2026, 3, 3), "Allocate eating out", Decimal(40), "Unallocated", "Eating out"
    ).unwrap()

    result = QueryAccountBalance(session).execute("Cash")

    assert result.is_ok
    balances = result.unwrap()
    assert len(balances) == 1
    assert balances[0].unit_identifier == "EUR"
    # The rollup nets to the lump sum: sibling-to-sibling transfers within
    # the subtree cancel out, however deep the destination sits.
    assert balances[0].quantity == Decimal(200)
