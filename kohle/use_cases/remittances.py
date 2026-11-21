from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import uuid4

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    ListPendingRemittancesError,
    NotARemittance,
    RemittanceCompleted,
    RemittanceError,
    RemittanceNotCompleted,
)
from kohle.domain.models import Classification, ClassificationKind, JournalEntry
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.classification_services import (
    classification_by_entry_service,
    pending_remittances_service,
    set_completion_service,
)
from kohle.services.journal_services import entry_by_id_service
from kohle.use_cases.conditions import Direction
from kohle.use_cases.lots import line_costs
from kohle.use_cases.posting import (
    Total,
    _cross_unit_lines,
    counterpart_line,
    post_entry,
    post_reversal,
    statement_amount,
    statement_line,
)


@dataclass(frozen=True, slots=True)
class PendingRemittance:
    entry_id: int
    entry_date: date
    description: str
    direction: Direction
    amount: Decimal  # unsigned: the direction says which way it went
    account_name: str  # the euro account
    counterpart_name: str
    unit_identifier: str


class ListPendingRemittances(UnitOfWork[list[PendingRemittance], ListPendingRemittancesError]):
    """Remittances waiting for their other half. A separate listing from
    list-unclassified: a rule has classified them, and what they need is an
    amount, through a different command."""

    def execute(self) -> Result[list[PendingRemittance], ListPendingRemittancesError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[PendingRemittance], ListPendingRemittancesError]:
            def convert(classifications):
                out = []
                for c in classifications:
                    amount = statement_amount(c)
                    assert c.remittance_account is not None and c.remittance_unit is not None
                    out.append(
                        PendingRemittance(
                            entry_id=c.entry.id,
                            entry_date=c.entry.entry_date,
                            description=c.entry.description,
                            direction=Direction.outgoing if amount < 0 else Direction.incoming,
                            amount=abs(amount),
                            account_name=statement_line(c).account.name,
                            counterpart_name=c.remittance_account.name,
                            unit_identifier=c.remittance_unit.identifier,
                        )
                    )
                return out

            return pending_remittances_service(ctx).map(convert)

        return self._run(use_case)


def complete_remittance(
    ctx: DbTransactionContext, classification: Classification, quantity: Decimal
) -> Result[JournalEntry, RemittanceError]:
    """Posts the two-amount entry that turns a pending remittance into a lot (or,
    incoming, a disposal of lots), dated at the original line so FIFO sees it the
    day the euros moved. Takes the ctx so an importer can call it from inside
    its own transaction when its currency row is the remittance's mirror."""
    entry_id = classification.journal_entry_id
    if classification.kind != ClassificationKind.remittance:
        return Result.err(NotARemittance(entry_id))
    if classification.completion_entry_id is not None:
        return Result.err(RemittanceCompleted(entry_id, classification.completion_entry_id))
    assert classification.remittance_account_id is not None and classification.remittance_unit_id is not None

    entry = classification.entry
    outgoing = statement_amount(classification) < 0
    lines = _cross_unit_lines(
        holding_account_id=classification.remittance_account_id,
        holding_unit_id=classification.remittance_unit_id,
        quantity=quantity,
        unit_price=Total(abs(statement_amount(classification))),
        cash_account_id=classification.final_account_id,
        cash_unit_id=counterpart_line(classification).unit_id,
        into_holding=outgoing,
    )
    posted_res = post_entry(ctx, entry.entry_date, uuid4().hex, f"Complete: {entry.description}", lines)
    if posted_res.is_err:
        return Result.err(posted_res.unwrap_err())
    posted = posted_res.unwrap()

    set_res = set_completion_service(ctx, classification.id, posted.id)
    if set_res.is_err:
        return Result.err(set_res.unwrap_err())

    if not outgoing:
        # A disposal of lots is only refused at read time elsewhere; replaying
        # here makes a shortfall roll the completion back.
        costs_res = line_costs(ctx, posted.lines)
        if costs_res.is_err:
            return Result.err(costs_res.unwrap_err())
    return Result.ok(posted)


@dataclass(frozen=True, slots=True)
class CompletedRemittance:
    completion_entry_id: int
    quantity: Decimal
    unit_identifier: str
    euros: Decimal


class CompleteRemittance(UnitOfWork[CompletedRemittance, RemittanceError]):
    def execute(self, entry_id: int, quantity: Decimal) -> Result[CompletedRemittance, RemittanceError]:
        def use_case(ctx: DbTransactionContext) -> Result[CompletedRemittance, RemittanceError]:
            classification_res = classification_by_entry_service(ctx, entry_id)
            if classification_res.is_err:
                return Result.err(classification_res.unwrap_err())
            classification = classification_res.unwrap()
            completed_res = complete_remittance(ctx, classification, quantity)
            if completed_res.is_err:
                return Result.err(completed_res.unwrap_err())
            assert classification.remittance_unit is not None
            return Result.ok(
                CompletedRemittance(
                    completion_entry_id=completed_res.unwrap().id,
                    quantity=quantity,
                    unit_identifier=classification.remittance_unit.identifier,
                    euros=abs(statement_amount(classification)),
                )
            )

        return self._run(use_case)


def uncomplete_remittance(ctx: DbTransactionContext, classification: Classification) -> Result[JournalEntry, RemittanceError]:
    """Reverses the completion by an entry the lot replay pairs with it, so the
    lots come back exactly and no gain stays booked. Mirroring the lines as an
    ordinary entry would instead book a new lot (incoming) or take the oldest
    lot (outgoing)."""
    entry_id = classification.journal_entry_id
    if classification.kind != ClassificationKind.remittance:
        return Result.err(NotARemittance(entry_id))
    if classification.completion_entry_id is None:
        return Result.err(RemittanceNotCompleted(entry_id))

    completion_res = entry_by_id_service(ctx, classification.completion_entry_id)
    if completion_res.is_err:
        return Result.err(completion_res.unwrap_err())
    completion = completion_res.unwrap()

    reversal_res = post_reversal(ctx, completion, f"Uncomplete: {classification.entry.description}")
    if reversal_res.is_err:
        return Result.err(reversal_res.unwrap_err())
    reversal = reversal_res.unwrap()

    set_res = set_completion_service(ctx, classification.id, None)
    if set_res.is_err:
        return Result.err(set_res.unwrap_err())

    if statement_amount(classification) < 0:
        # Removing the lot an outgoing completion made can starve a later
        # spend; the shortfall is otherwise only found when a report is read.
        costs_res = line_costs(ctx, reversal.lines)
        if costs_res.is_err:
            return Result.err(costs_res.unwrap_err())
    return Result.ok(reversal)


class UncompleteRemittance(UnitOfWork[JournalEntry, RemittanceError]):
    def execute(self, entry_id: int) -> Result[JournalEntry, RemittanceError]:
        def use_case(ctx: DbTransactionContext) -> Result[JournalEntry, RemittanceError]:
            classification_res = classification_by_entry_service(ctx, entry_id)
            if classification_res.is_err:
                return Result.err(classification_res.unwrap_err())
            return uncomplete_remittance(ctx, classification_res.unwrap())

        return self._run(use_case)
