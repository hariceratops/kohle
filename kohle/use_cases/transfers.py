from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AccountError,
    ClassificationError,
    JournalError,
    ListUnmirroredError,
)
from kohle.domain.models import Classification, JournalEntry
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import list_accounts_service
from kohle.services.classification_services import (
    first_statement_dates_service,
    open_transfers_service,
    rerun_candidates_service,
    set_mirror_service,
)
from kohle.use_cases.conditions import normalise_iban
from kohle.use_cases.posting import post_correction, statement_amount, statement_line

TransferError = AccountError | JournalError | ClassificationError

# The user's figure, not a setting.
MIRROR_WINDOW_DAYS = 3


@dataclass(frozen=True, slots=True)
class TransferSide:
    entry_id: int
    entry_date: date
    amount: Decimal  # signed, on the statement the transfer was made from
    counterpart_id: int
    source_iban: str | None  # the statement account's IBAN, normalised, if it has one


@dataclass(frozen=True, slots=True)
class RowSide:
    entry_date: date
    amount: Decimal  # signed, on the counterpart's statement
    counterparty_iban: str | None


def is_mirror(transfer: TransferSide, row: RowSide) -> bool:
    """Opposite direction and exactly equal are one comparison; the IBANs are
    compared only when both are known."""
    return (
        row.amount == -transfer.amount
        and abs((row.entry_date - transfer.entry_date).days) <= MIRROR_WINDOW_DAYS
        and (
            transfer.source_iban is None
            or row.counterparty_iban is None
            or normalise_iban(row.counterparty_iban) == transfer.source_iban
        )
    )


def nearest_transfer(row: RowSide, transfers: Iterable[TransferSide]) -> TransferSide | None:
    """Nearest date first, then the earlier transfer, then the lower entry id:
    a total order, so pairing is deterministic."""
    hits = [transfer for transfer in transfers if is_mirror(transfer, row)]
    return min(
        hits,
        key=lambda transfer: (abs((row.entry_date - transfer.entry_date).days), transfer.entry_date, transfer.entry_id),
        default=None,
    )


def nearest_row(transfer: TransferSide, rows: Iterable[tuple[int, RowSide]]) -> int | None:
    """The entry id of the nearest row that mirrors `transfer`; ties go to the
    earlier date, then the lower entry id."""
    hits = [(entry_id, row) for entry_id, row in rows if is_mirror(transfer, row)]
    if not hits:
        return None
    entry_id, _ = min(
        hits,
        key=lambda hit: (abs((hit[1].entry_date - transfer.entry_date).days), hit[1].entry_date, hit[0]),
    )
    return entry_id


def account_ibans(ctx: DbTransactionContext) -> Result[dict[int, str | None], AccountError]:
    return list_accounts_service(ctx).map(
        lambda accounts: {
            account.id: normalise_iban(account.iban) if account.iban else None for account in accounts
        }
    )


def row_side(classification: Classification) -> RowSide:
    entry = classification.entry
    return RowSide(entry.entry_date, statement_amount(classification), entry.counterparty_iban)


def _transfer_side(transfer: Classification, ibans: dict[int, str | None]) -> TransferSide:
    entry = transfer.entry
    return TransferSide(
        entry.id,
        entry.entry_date,
        statement_amount(transfer),
        transfer.final_account_id,
        ibans[statement_line(transfer).account_id],
    )


def open_transfers_into(
    ctx: DbTransactionContext, account_id: int, ibans: dict[int, str | None]
) -> Result[list[TransferSide], ClassificationError]:
    """The transfers into `account_id` that no row has been absorbed into yet."""
    return open_transfers_service(ctx, account_id).map(
        lambda transfers: [_transfer_side(transfer, ibans) for transfer in transfers]
    )


def absorb(
    ctx: DbTransactionContext, mirror: Classification, transfer_entry_id: int, *, by_human: bool
) -> Result[JournalEntry, TransferError]:
    """Cancel a fall-through onto its own account and record which transfer it
    joined. The row stays posted as the import posted it, so its native
    reference is kept and the pair nets to nothing."""
    own_account_id = statement_line(mirror).account_id
    posted = post_correction(ctx, mirror, own_account_id, f"Mirror: {mirror.entry.description}")
    if posted.is_err:
        return posted
    outcome = set_mirror_service(ctx, mirror.id, own_account_id, transfer_entry_id, by_human)
    if outcome.is_err:
        return Result.err(outcome.unwrap_err())
    return posted


def absorb_counterpart_fall_through(
    ctx: DbTransactionContext,
    transfer: Classification,
    bucket_ids: Iterable[int],
    ibans: dict[int, str | None],
) -> Result[int | None, TransferError]:
    """After a transfer is posted, absorb the untouched fall-through of the
    counterpart account that mirrors it, if there is one. Returns that row's
    entry id."""
    side = _transfer_side(transfer, ibans)
    candidates_res = rerun_candidates_service(ctx, bucket_ids, statement_account_id=side.counterpart_id)
    if candidates_res.is_err:
        return Result.err(candidates_res.unwrap_err())
    candidates = {candidate.journal_entry_id: candidate for candidate in candidates_res.unwrap()}
    rows = [
        (entry_id, row_side(c)) for entry_id, c in candidates.items()
    ]
    picked = nearest_row(side, rows)
    if picked is None:
        return Result.ok(None)
    absorbed = absorb(ctx, candidates[picked], side.entry_id, by_human=False)
    if absorbed.is_err:
        return Result.err(absorbed.unwrap_err())
    return Result.ok(picked)


@dataclass(frozen=True, slots=True)
class UnmirroredTransfer:
    entry_id: int
    entry_date: date
    description: str
    amount: Decimal  # signed, on the statement the transfer was made from
    account_name: str  # that statement's account
    counterpart_name: str


class ListUnmirroredTransfers(UnitOfWork[list[UnmirroredTransfer], ListUnmirroredError]):
    """Transfers whose mirror has not arrived, so a late or missing row shows.

    Only counterparts that have had a statement imported are considered, and
    only transfers no earlier than that statement's first row minus the
    window: a mirror dated before the first import will never arrive."""

    def execute(self) -> Result[list[UnmirroredTransfer], ListUnmirroredError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[UnmirroredTransfer], ListUnmirroredError]:
            open_res = open_transfers_service(ctx)
            if open_res.is_err:
                return Result.err(open_res.unwrap_err())
            transfers = open_res.unwrap()
            firsts_res = first_statement_dates_service(ctx, {t.final_account_id for t in transfers})
            if firsts_res.is_err:
                return Result.err(firsts_res.unwrap_err())
            firsts = firsts_res.unwrap()
            accounts_res = list_accounts_service(ctx)
            if accounts_res.is_err:
                return Result.err(accounts_res.unwrap_err())
            names = {account.id: account.name for account in accounts_res.unwrap()}
            window = timedelta(days=MIRROR_WINDOW_DAYS)
            return Result.ok(
                [
                    UnmirroredTransfer(
                        entry_id=transfer.entry.id,
                        entry_date=transfer.entry.entry_date,
                        description=transfer.entry.description,
                        amount=statement_amount(transfer),
                        account_name=names[statement_line(transfer).account_id],
                        counterpart_name=names[transfer.final_account_id],
                    )
                    for transfer in transfers
                    if transfer.final_account_id in firsts
                    and transfer.entry.entry_date >= firsts[transfer.final_account_id] - window
                ]
            )

        return self._run(use_case)
