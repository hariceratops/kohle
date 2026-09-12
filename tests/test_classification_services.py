"""Layer 2 — service tests against the `session` fixture.

The classification record (issues 015, 016, 017).

The predicate `unclassified_classifications_service` uses is the one the spec
gets wrong: it offers `matched_rule_id IS NULL` and `final_account_id IN
(buckets)` as equivalent, and they diverge permanently once a fall-through row
is corrected. dev/design/expense-classification.md §6.1 chooses the second,
which is also why issue 016 needs no code change when 017 lands.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from kohle.domain.domain_errors import ClassificationError
from kohle.domain.models import AccountType, Classification, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import add_account_service
from kohle.services.classification_services import (
    add_classification_service,
    set_classification_outcome_service,
    unclassified_classifications_service,
)
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.rule_services import add_rule_service
from kohle.services.unit_services import add_unit_service


class _Ledger:
    """Accounts, a unit and a rule to hang a classification off."""

    def __init__(self, ctx: DbTransactionContext) -> None:
        self.checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
        self.groceries = add_account_service(ctx, "Groceries", AccountType.expense).unwrap().id
        self.bucket = add_account_service(ctx, "Unclassified Expense", AccountType.expense).unwrap().id
        self.eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
        self.rule = add_rule_service(ctx, "REWE", self.groceries, 100).unwrap().id

    def entry(self, ctx: DbTransactionContext, reference: str, counterpart_id: int) -> int:
        value = Decimal(80)
        lines = [
            LineSpec(counterpart_id, self.eur, value, Decimal(1), is_debit=True),
            LineSpec(self.checking, self.eur, value, Decimal(1), is_debit=False),
        ]
        return add_journal_entry_service(ctx, date(2026, 3, 1), reference, "REWE SAGT DANKE", lines).unwrap().id


def test_a_matched_row_records_the_rule_that_sent_it(session: Session) -> None:
    ctx = DbTransactionContext(session)
    ledger = _Ledger(ctx)
    entry_id = ledger.entry(ctx, "ref-1", ledger.groceries)

    result = add_classification_service(
        ctx,
        journal_entry_id=entry_id,
        proposed_account_id=ledger.groceries,
        matched_rule_id=ledger.rule,
        final_account_id=ledger.groceries,
    )

    assert result.is_ok
    classification = result.unwrap()
    assert classification.matched_rule_id == ledger.rule
    # Proposed and final agree at import on both paths; they diverge only once
    # a human corrects the line, and that divergence is the whole record.
    assert classification.proposed_account_id == ledger.groceries
    assert classification.final_account_id == ledger.groceries
    assert classification.corrected is False


def test_a_fall_through_row_is_recorded_too(session: Session) -> None:
    ctx = DbTransactionContext(session)
    ledger = _Ledger(ctx)
    entry_id = ledger.entry(ctx, "ref-2", ledger.bucket)

    result = add_classification_service(
        ctx,
        journal_entry_id=entry_id,
        proposed_account_id=ledger.bucket,
        matched_rule_id=None,
        final_account_id=ledger.bucket,
    )

    assert result.is_ok
    classification = result.unwrap()
    # NULL is the encoding for "no rule matched", which is why a removed rule
    # is retired rather than deleted — a tombstone here would be unreadable.
    assert classification.matched_rule_id is None
    assert classification.proposed_account_id == ledger.bucket
    assert classification.final_account_id == ledger.bucket


def test_one_entry_cannot_hold_two_classifications(session: Session) -> None:
    ctx = DbTransactionContext(session)
    ledger = _Ledger(ctx)
    entry_id = ledger.entry(ctx, "ref-3", ledger.groceries)

    assert add_classification_service(
        ctx,
        journal_entry_id=entry_id,
        proposed_account_id=ledger.groceries,
        matched_rule_id=ledger.rule,
        final_account_id=ledger.groceries,
    ).is_ok

    result = add_classification_service(
        ctx,
        journal_entry_id=entry_id,
        proposed_account_id=ledger.bucket,
        matched_rule_id=None,
        final_account_id=ledger.bucket,
    )

    # "The classification of this line" has one referent: correcting one is an
    # update rather than an append, and no read needs a max-per-entry subquery.
    assert result.is_err
    assert isinstance(result.unwrap_err(), ClassificationError)
    session.rollback()
    assert session.query(Classification).filter(Classification.journal_entry_id == entry_id).count() <= 1


def test_unclassified_classifications_returns_only_bucket_rows(session: Session) -> None:
    ctx = DbTransactionContext(session)
    ledger = _Ledger(ctx)
    matched_entry_id = ledger.entry(ctx, "ref-1", ledger.groceries)
    fallen_through_entry_id = ledger.entry(ctx, "ref-2", ledger.bucket)

    add_classification_service(
        ctx,
        journal_entry_id=matched_entry_id,
        proposed_account_id=ledger.groceries,
        matched_rule_id=ledger.rule,
        final_account_id=ledger.groceries,
    )
    add_classification_service(
        ctx,
        journal_entry_id=fallen_through_entry_id,
        proposed_account_id=ledger.bucket,
        matched_rule_id=None,
        final_account_id=ledger.bucket,
    )

    result = unclassified_classifications_service(ctx, [ledger.bucket])

    assert result.is_ok
    rows = result.unwrap()
    assert [row.journal_entry_id for row in rows] == [fallen_through_entry_id]


def test_reading_and_correcting_classifications(session: Session) -> None:
    ctx = DbTransactionContext(session)
    ledger = _Ledger(ctx)
    entry_id = ledger.entry(ctx, "ref-2", ledger.bucket)
    classification = add_classification_service(
        ctx,
        journal_entry_id=entry_id,
        proposed_account_id=ledger.bucket,
        matched_rule_id=None,
        final_account_id=ledger.bucket,
    ).unwrap()

    result = set_classification_outcome_service(ctx, classification.id, ledger.groceries)

    assert result.is_ok
    corrected = result.unwrap()
    assert corrected.final_account_id == ledger.groceries
    assert corrected.corrected is True
    # The record of what the engine got wrong is left exactly as it was.
    assert corrected.proposed_account_id == ledger.bucket
    assert corrected.matched_rule_id is None

    # A corrected fall-through row drops out of the unclassified query even
    # though matched_rule_id is still NULL — the predicate filters on
    # final_account_id, not on whether a rule matched (§6.1).
    unclassified = unclassified_classifications_service(ctx, [ledger.bucket])
    assert unclassified.is_ok
    assert unclassified.unwrap() == []
