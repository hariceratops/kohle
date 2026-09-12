"""Layer 3 — use-case tests against the `session` fixture.

`Reclassify` (issue 017).

Correction is an adjusting entry; the original entry is never edited, voided
or deleted. The classification row, however, is updated — it is an annotation
about the ledger rather than part of it, which is the distinction
dev/design/expense-classification.md §7.2 draws to justify adding crud_update.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from kohle.domain.domain_errors import (
    AccountNotFoundError,
    NoClassificationForEntry,
    PostingToNonLeafAccount,
)
from kohle.domain.models import AccountType, Classification, JournalEntry, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import add_account_service
from kohle.services.classification_services import add_classification_service
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.rule_services import add_rule_service
from kohle.services.unit_services import add_unit_service
from kohle.use_cases.classification import Reclassify
from kohle.use_cases.journal import QueryAccountBalance


class _Ledger:
    """Accounts, a unit and a rule to hang a classification off."""

    def __init__(self, ctx: DbTransactionContext) -> None:
        self.checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
        self.groceries = add_account_service(ctx, "Groceries", AccountType.expense).unwrap().id
        self.books = add_account_service(ctx, "Books", AccountType.expense).unwrap().id
        self.bucket = add_account_service(ctx, "Unclassified Expense", AccountType.expense).unwrap().id
        self.eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
        self.rule = add_rule_service(ctx, "AMZN", self.books, 100).unwrap().id

    def entry(self, ctx: DbTransactionContext, reference: str, counterpart_id: int) -> int:
        value = Decimal(80)
        lines = [
            LineSpec(counterpart_id, self.eur, value, Decimal(1), is_debit=True),
            LineSpec(self.checking, self.eur, value, Decimal(1), is_debit=False),
        ]
        return add_journal_entry_service(
            ctx, date(2026, 3, 1), reference, "AMZN MARKETPLACE", lines
        ).unwrap().id


def _classify(ctx: DbTransactionContext, ledger: _Ledger, entry_id: int, proposed_id: int, rule_id: int | None) -> int:
    return add_classification_service(
        ctx,
        journal_entry_id=entry_id,
        proposed_account_id=proposed_id,
        matched_rule_id=rule_id,
        final_account_id=proposed_id,
    ).unwrap().id


def test_reclassify_a_wrong_match_posts_a_reversing_pair_and_leaves_the_original_untouched(
    session: Session,
) -> None:
    ctx = DbTransactionContext(session)
    ledger = _Ledger(ctx)
    entry_id = ledger.entry(ctx, "ref-1", ledger.books)
    _classify(ctx, ledger, entry_id, ledger.books, ledger.rule)
    session.commit()

    result = Reclassify(session).execute(entry_id, "Groceries")

    assert result.is_ok
    adjusting_entry = result.unwrap()
    assert adjusting_entry.id != entry_id
    assert len(adjusting_entry.lines) == 2
    by_account = {line.account_id: line for line in adjusting_entry.lines}
    assert by_account[ledger.books].is_debit is False
    assert by_account[ledger.books].value == Decimal(80)
    assert by_account[ledger.groceries].is_debit is True
    assert by_account[ledger.groceries].value == Decimal(80)
    # Dated the original entry's date, not today.
    assert adjusting_entry.entry_date == date(2026, 3, 1)

    original = session.get(JournalEntry, entry_id)
    assert len(original.lines) == 2
    assert {line.account_id for line in original.lines} == {ledger.books, ledger.checking}


def test_reclassify_updates_the_classification_and_keeps_proposed_and_rule(session: Session) -> None:
    ctx = DbTransactionContext(session)
    ledger = _Ledger(ctx)
    entry_id = ledger.entry(ctx, "ref-1", ledger.books)
    classification_id = _classify(ctx, ledger, entry_id, ledger.books, ledger.rule)
    session.commit()

    result = Reclassify(session).execute(entry_id, "Groceries")
    assert result.is_ok

    classification = session.get(Classification, classification_id)
    assert classification.final_account_id == ledger.groceries
    assert classification.corrected is True
    # The record of what the engine got wrong is left exactly as it was.
    assert classification.proposed_account_id == ledger.books
    assert classification.matched_rule_id == ledger.rule


def test_reclassify_a_fallen_through_line_works_the_same_way(session: Session) -> None:
    ctx = DbTransactionContext(session)
    ledger = _Ledger(ctx)
    entry_id = ledger.entry(ctx, "ref-1", ledger.bucket)
    classification_id = _classify(ctx, ledger, entry_id, ledger.bucket, None)
    session.commit()

    result = Reclassify(session).execute(entry_id, "Groceries")

    assert result.is_ok
    classification = session.get(Classification, classification_id)
    assert classification.final_account_id == ledger.groceries
    assert classification.corrected is True
    assert classification.proposed_account_id == ledger.bucket
    assert classification.matched_rule_id is None


def test_reclassify_moves_the_balance_off_the_wrong_account_onto_the_right_one(session: Session) -> None:
    ctx = DbTransactionContext(session)
    ledger = _Ledger(ctx)
    entry_id = ledger.entry(ctx, "ref-1", ledger.books)
    _classify(ctx, ledger, entry_id, ledger.books, ledger.rule)
    session.commit()

    result = Reclassify(session).execute(entry_id, "Groceries")
    assert result.is_ok

    books_balance = QueryAccountBalance(session).execute("Books").unwrap()
    groceries_balance = QueryAccountBalance(session).execute("Groceries").unwrap()
    assert books_balance == [] or all(b.quantity == 0 for b in books_balance)
    assert any(b.quantity == Decimal(80) for b in groceries_balance)


def test_reclassify_an_unknown_entry_id_reports_no_classification(session: Session) -> None:
    result = Reclassify(session).execute(999, "Groceries")
    assert result.is_err
    assert isinstance(result.unwrap_err(), NoClassificationForEntry)


def test_reclassify_an_unknown_target_account_reports_it(session: Session) -> None:
    ctx = DbTransactionContext(session)
    ledger = _Ledger(ctx)
    entry_id = ledger.entry(ctx, "ref-1", ledger.books)
    _classify(ctx, ledger, entry_id, ledger.books, ledger.rule)
    session.commit()

    result = Reclassify(session).execute(entry_id, "Nope")
    assert result.is_err
    assert isinstance(result.unwrap_err(), AccountNotFoundError)


def test_reclassify_a_non_leaf_target_account_is_rejected(session: Session) -> None:
    ctx = DbTransactionContext(session)
    ledger = _Ledger(ctx)
    living = add_account_service(ctx, "Living", AccountType.expense).unwrap().id
    add_account_service(ctx, "Rent", AccountType.expense, None, living)
    session.commit()
    entry_id = ledger.entry(ctx, "ref-1", ledger.books)
    _classify(ctx, ledger, entry_id, ledger.books, ledger.rule)
    session.commit()

    result = Reclassify(session).execute(entry_id, "Living")
    assert result.is_err
    assert isinstance(result.unwrap_err(), PostingToNonLeafAccount)


def test_a_double_reclassify_lands_the_amount_on_the_final_account(session: Session) -> None:
    """bucket -> A -> B leaves A and the bucket both at zero: the reversal
    comes out of final_account_id, not proposed_account_id, from the second
    correction onward (design §7.1)."""
    ctx = DbTransactionContext(session)
    ledger = _Ledger(ctx)
    entry_id = ledger.entry(ctx, "ref-1", ledger.bucket)
    _classify(ctx, ledger, entry_id, ledger.bucket, None)
    session.commit()

    first = Reclassify(session).execute(entry_id, "Books")
    assert first.is_ok
    second = Reclassify(session).execute(entry_id, "Groceries")
    assert second.is_ok

    bucket_balance = QueryAccountBalance(session).execute("Unclassified Expense").unwrap()
    books_balance = QueryAccountBalance(session).execute("Books").unwrap()
    groceries_balance = QueryAccountBalance(session).execute("Groceries").unwrap()

    assert bucket_balance == [] or all(b.quantity == 0 for b in bucket_balance)
    assert books_balance == [] or all(b.quantity == 0 for b in books_balance)
    assert any(b.quantity == Decimal(80) for b in groceries_balance)

    classification = session.query(Classification).filter_by(journal_entry_id=entry_id).one()
    assert classification.final_account_id == ledger.groceries
    assert classification.proposed_account_id == ledger.bucket
    assert classification.corrected is True
