"""Layer 2 — join, unjoin, reclassify and split-line on transfers (issues 129-131). Design §18.4."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    InvalidTransferTarget,
    IsAMirror,
    NotAFallThrough,
    NotAMirror,
    NotATransfer,
    NotSplittable,
    NotTheMirror,
    TransferHasMirror,
)
from kohle.domain.models import (
    Account,
    AccountType,
    Classification,
    ClassificationKind,
    JournalEntry,
    JournalLine,
    OperationGroup,
)
from kohle.use_cases import classification as classification_module
from kohle.use_cases import transfers as transfers_module
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.classification import (
    ListUnclassified,
    PlanClassifyRules,
    Reclassify,
)
from kohle.use_cases.journal import ImportStatement
from kohle.use_cases.rules import ApplyRuleFile, PlanRuleFile
from kohle.use_cases.splitting import SplitImportedEntry
from kohle.use_cases.transfers import (
    JoinTransfer,
    ListUnmirroredTransfers,
    UnjoinTransfer,
)

SAVINGS_IBAN = "DE44500105175407324931"


def _transfer_rule(account: str, iban: str = SAVINGS_IBAN) -> str:
    text = f'[[rule]]\ntransfer = "{account}"\n[rule.when]\niban = "{iban}"\n'
    return text


def _ledger(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset)
    AddAccount(session).execute("Savings", AccountType.asset)
    text = _transfer_rule("Savings")
    plan = PlanRuleFile(session).execute(text).unwrap()
    ApplyRuleFile(session).execute(text, plan.base).unwrap()


def _entry_id(session: Session, description: str) -> int:
    return session.query(JournalEntry).filter(JournalEntry.description == description).one().id


def _balances(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Account.name, func.sum(JournalLine.quantity * func.iif(JournalLine.is_debit, 1, -1)))
        .join(JournalLine, JournalLine.account_id == Account.id)
        .group_by(Account.name)
    ).all()
    return {name: int(total) for name, total in rows}


def _classification(session: Session, description: str) -> Classification:
    return session.query(Classification).filter(Classification.journal_entry_id == _entry_id(session, description)).one()


def _state(session: Session) -> tuple[int, int]:
    return session.query(JournalEntry).count(), session.query(OperationGroup).count()


def _late(session: Session, cash_rows, statement_row, *savings_rows: dict) -> None:
    """A transfer on 04-03, then Savings' statement: by default its row for the
    transfer five days late, which the import leaves as a fall-through."""
    _ledger(session)
    ImportStatement(session).execute(
        "Checking",
        cash_rows([statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika", SAVINGS_IBAN)]),
    ).unwrap()
    rows = savings_rows or (statement_row(date(2026, 4, 8), 500, "From checking", "Erika"),)
    ImportStatement(session).execute("Savings", cash_rows(list(rows))).unwrap()


def test_a_late_fall_through_is_joined_to_its_transfer_in_one_group(
    session: Session, cash_rows, statement_row
) -> None:
    _late(session, cash_rows, statement_row)
    line, transfer = _entry_id(session, "From checking"), _entry_id(session, "Move to savings")
    assert _balances(session) == {"Checking": -500, "Savings": 1000, "Unclassified Income": -500}
    entries, groups = _state(session)

    assert JoinTransfer(session).execute(line, transfer).is_ok

    assert _balances(session) == {"Checking": -500, "Savings": 500, "Unclassified Income": 0}
    assert _state(session) == (entries + 1, groups + 1)
    mirror = _classification(session, "From checking")
    assert (mirror.kind, mirror.mirror_of_entry_id, mirror.corrected) == (ClassificationKind.mirror, transfer, True)
    assert mirror.final_account.name == "Savings"
    assert ListUnmirroredTransfers(session).execute().unwrap() == []
    assert ListUnclassified(session).execute().unwrap() == []


def test_a_join_is_distinguishable_from_a_rule_made_transfer_and_a_category_correction(
    session: Session, cash_rows, statement_row
) -> None:
    _late(session, cash_rows, statement_row)
    JoinTransfer(session).execute(_entry_id(session, "From checking"), _entry_id(session, "Move to savings")).unwrap()

    transfer = _classification(session, "Move to savings")
    mirror = _classification(session, "From checking")

    assert (transfer.kind, transfer.corrected) == (ClassificationKind.transfer, False)
    assert (mirror.kind, mirror.corrected) == (ClassificationKind.mirror, True)


def test_joining_refuses_a_line_that_is_not_a_fall_through(session: Session, cash_rows, statement_row) -> None:
    _late(session, cash_rows, statement_row)
    transfer = _entry_id(session, "Move to savings")
    entries, groups = _state(session)

    res = JoinTransfer(session).execute(transfer, transfer)

    assert isinstance(res.unwrap_err(), NotAFallThrough)
    assert _state(session) == (entries, groups)


def test_joining_refuses_a_line_that_a_human_moved_off_the_bucket(
    session: Session, cash_rows, statement_row
) -> None:
    _late(session, cash_rows, statement_row)
    AddAccount(session).execute("Gifts", AccountType.income).unwrap()
    line = _entry_id(session, "From checking")
    Reclassify(session).execute(line, "Gifts").unwrap()

    res = JoinTransfer(session).execute(line, _entry_id(session, "Move to savings"))

    assert isinstance(res.unwrap_err(), NotAFallThrough)


def test_joining_refuses_a_target_that_is_not_a_transfer(session: Session, cash_rows, statement_row) -> None:
    _late(
        session, cash_rows, statement_row,
        statement_row(date(2026, 4, 8), 500, "From checking", "Erika"),
        statement_row(date(2026, 4, 9), 7, "Interest", "Bank"),
    )

    res = JoinTransfer(session).execute(_entry_id(session, "From checking"), _entry_id(session, "Interest"))

    assert isinstance(res.unwrap_err(), NotATransfer)


def test_joining_refuses_a_transfer_that_already_has_a_mirror(session: Session, cash_rows, statement_row) -> None:
    _late(
        session, cash_rows, statement_row,
        statement_row(date(2026, 4, 4), 500, "Early", "Erika"),
        statement_row(date(2026, 4, 9), 500, "Late", "Erika"),
    )
    transfer = _entry_id(session, "Move to savings")
    early = _entry_id(session, "Early")
    entries, groups = _state(session)

    res = JoinTransfer(session).execute(_entry_id(session, "Late"), transfer)

    err = res.unwrap_err()
    assert isinstance(err, TransferHasMirror)
    assert err.mirror_id == early
    assert f"unjoin-transfer {early}" in str(err)
    assert _state(session) == (entries, groups)


def test_joining_refuses_a_line_imported_into_another_account(session: Session, cash_rows, statement_row) -> None:
    _late(session, cash_rows, statement_row)
    ImportStatement(session).execute(
        "Checking", cash_rows([statement_row(date(2026, 4, 6), 500, "Refund", "Shop", reference="refund")])
    ).unwrap()

    res = JoinTransfer(session).execute(_entry_id(session, "Refund"), _entry_id(session, "Move to savings"))

    err = res.unwrap_err()
    assert isinstance(err, NotTheMirror)
    assert "imported into Checking, not Savings" in str(err)


def test_joining_refuses_a_line_with_a_different_amount(session: Session, cash_rows, statement_row) -> None:
    _late(session, cash_rows, statement_row, statement_row(date(2026, 4, 8), 450, "Short", "Erika"))

    res = JoinTransfer(session).execute(_entry_id(session, "Short"), _entry_id(session, "Move to savings"))

    err = res.unwrap_err()
    assert isinstance(err, NotTheMirror)
    assert "its amount is 450.00, the transfer's is -500.00" in str(err)


def test_joining_refuses_a_line_in_the_same_direction(session: Session, cash_rows, statement_row) -> None:
    _late(session, cash_rows, statement_row, statement_row(date(2026, 4, 8), -500, "Same way", "Erika"))
    entries, groups = _state(session)

    res = JoinTransfer(session).execute(_entry_id(session, "Same way"), _entry_id(session, "Move to savings"))

    assert isinstance(res.unwrap_err(), NotTheMirror)
    assert _state(session) == (entries, groups)


def test_a_fault_while_joining_writes_nothing(
    session: Session, cash_rows, statement_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    _late(session, cash_rows, statement_row)
    line, transfer = _entry_id(session, "From checking"), _entry_id(session, "Move to savings")
    entries, groups = _state(session)
    before = _balances(session)
    monkeypatch.setattr(transfers_module, "set_mirror_service", lambda *a, **k: Result.err(RuntimeError("boom")))

    assert JoinTransfer(session).execute(line, transfer).is_err

    assert _state(session) == (entries, groups)
    assert _balances(session) == before
    assert _classification(session, "From checking").kind == ClassificationKind.category


def test_a_fault_while_unjoining_writes_nothing(
    session: Session, cash_rows, statement_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    _late(session, cash_rows, statement_row)
    line, transfer = _entry_id(session, "From checking"), _entry_id(session, "Move to savings")
    JoinTransfer(session).execute(line, transfer).unwrap()
    entries, groups = _state(session)
    before = _balances(session)
    monkeypatch.setattr(transfers_module, "clear_mirror_service", lambda *a, **k: Result.err(RuntimeError("boom")))

    assert UnjoinTransfer(session).execute(line).is_err

    assert _state(session) == (entries, groups)
    assert _balances(session) == before
    assert _classification(session, "From checking").kind == ClassificationKind.mirror


def test_unjoining_puts_the_row_back_in_its_bucket_as_a_human_corrected_fall_through(
    session: Session, cash_rows, statement_row
) -> None:
    _late(session, cash_rows, statement_row)
    line, transfer = _entry_id(session, "From checking"), _entry_id(session, "Move to savings")
    JoinTransfer(session).execute(line, transfer).unwrap()
    entries, groups = _state(session)

    assert UnjoinTransfer(session).execute(line).is_ok

    assert _balances(session) == {"Checking": -500, "Savings": 1000, "Unclassified Income": -500}
    assert _state(session) == (entries + 1, groups + 1)
    row = _classification(session, "From checking")
    assert (row.kind, row.mirror_of_entry_id, row.corrected) == (ClassificationKind.category, None, True)
    assert [u.entry_id for u in ListUnclassified(session).execute().unwrap()] == [line]


def test_an_unjoined_row_is_left_alone_by_classify_rules(session: Session, cash_rows, statement_row) -> None:
    _late(session, cash_rows, statement_row)
    line, transfer = _entry_id(session, "From checking"), _entry_id(session, "Move to savings")
    JoinTransfer(session).execute(line, transfer).unwrap()
    UnjoinTransfer(session).execute(line).unwrap()

    assert PlanClassifyRules(session).execute().unwrap() == []


def test_an_unjoined_row_can_be_joined_again(session: Session, cash_rows, statement_row) -> None:
    _late(session, cash_rows, statement_row)
    line, transfer = _entry_id(session, "From checking"), _entry_id(session, "Move to savings")
    JoinTransfer(session).execute(line, transfer).unwrap()
    UnjoinTransfer(session).execute(line).unwrap()

    assert JoinTransfer(session).execute(line, transfer).is_ok

    assert _balances(session) == {"Checking": -500, "Savings": 500, "Unclassified Income": 0}


def test_unjoining_a_line_a_rule_first_sent_elsewhere_returns_it_to_the_bucket(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    AddAccount(session).execute("Gifts", AccountType.income).unwrap()
    text = _transfer_rule("Savings") + '\n[[rule]]\naccount = "Gifts"\n[rule.when]\ndescription = "From checking"\n'
    plan = PlanRuleFile(session).execute(text).unwrap()
    ApplyRuleFile(session).execute(text, plan.base).unwrap()
    ImportStatement(session).execute(
        "Checking",
        cash_rows([statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika", SAVINGS_IBAN)]),
    ).unwrap()
    ImportStatement(session).execute(
        "Savings", cash_rows([statement_row(date(2026, 4, 8), 500, "From checking", "Erika")])
    ).unwrap()
    line, transfer = _entry_id(session, "From checking"), _entry_id(session, "Move to savings")
    Reclassify(session).execute(line, "Unclassified Income").unwrap()
    JoinTransfer(session).execute(line, transfer).unwrap()

    UnjoinTransfer(session).execute(line).unwrap()

    row = _classification(session, "From checking")
    assert row.final_account.name == "Unclassified Income"
    assert _balances(session)["Gifts"] == 0


def test_unjoining_refuses_a_line_that_is_not_a_mirror(session: Session, cash_rows, statement_row) -> None:
    _late(session, cash_rows, statement_row)
    entries, groups = _state(session)

    res = UnjoinTransfer(session).execute(_entry_id(session, "From checking"))

    assert isinstance(res.unwrap_err(), NotAMirror)
    assert _state(session) == (entries, groups)


def test_a_transfer_to_an_account_with_a_statement_is_listed_until_its_mirror_arrives(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Savings", cash_rows([statement_row(date(2026, 4, 1), 10, "Interest", "Bank")])
    ).unwrap()
    ImportStatement(session).execute(
        "Checking",
        cash_rows([statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika", SAVINGS_IBAN)]),
    ).unwrap()

    listed = ListUnmirroredTransfers(session).execute().unwrap()

    assert [(t.entry_date, t.description, t.amount, t.account_name, t.counterpart_name) for t in listed] == [
        (date(2026, 4, 3), "Move to savings", -500, "Checking", "Savings")
    ]


def test_a_transfer_to_a_counterpart_never_imported_is_not_listed(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Checking",
        cash_rows([statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika", SAVINGS_IBAN)]),
    ).unwrap()

    assert ListUnmirroredTransfers(session).execute().unwrap() == []


def test_a_transfer_whose_mirror_was_absorbed_is_not_listed(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Checking",
        cash_rows([statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika", SAVINGS_IBAN)]),
    ).unwrap()
    ImportStatement(session).execute(
        "Savings", cash_rows([statement_row(date(2026, 4, 4), 500, "From checking", "Erika")])
    ).unwrap()

    assert ListUnmirroredTransfers(session).execute().unwrap() == []


def test_a_transfer_older_than_the_first_statement_row_by_more_than_the_window_is_not_listed(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Checking",
        cash_rows([
            statement_row(date(2026, 4, 1), -100, "Early", "Erika", SAVINGS_IBAN, reference="a"),
            statement_row(date(2026, 4, 7), -200, "Edge", "Erika", SAVINGS_IBAN, reference="b"),
        ]),
    ).unwrap()
    ImportStatement(session).execute(
        "Savings", cash_rows([statement_row(date(2026, 4, 10), 1, "Interest", "Bank")])
    ).unwrap()

    listed = ListUnmirroredTransfers(session).execute().unwrap()

    assert [t.description for t in listed] == ["Edge"]


def test_listing_writes_no_operation_group(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Savings", cash_rows([statement_row(date(2026, 4, 1), 10, "Interest", "Bank")])
    ).unwrap()
    ImportStatement(session).execute(
        "Checking",
        cash_rows([statement_row(date(2026, 4, 3), -500, "Move", "Erika", SAVINGS_IBAN)]),
    ).unwrap()
    before = session.query(OperationGroup).count()

    ListUnmirroredTransfers(session).execute().unwrap()

    assert session.query(OperationGroup).count() == before


def _absorbed(session: Session, cash_rows, statement_row) -> tuple[int, int]:
    """A transfer on 04-03 whose mirror arrives in time and is absorbed."""
    _ledger(session)
    AddAccount(session).execute("Gifts", AccountType.expense).unwrap()
    AddAccount(session).execute("Brokerage", AccountType.asset).unwrap()
    ImportStatement(session).execute(
        "Checking",
        cash_rows([statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika", SAVINGS_IBAN)]),
    ).unwrap()
    ImportStatement(session).execute(
        "Savings", cash_rows([statement_row(date(2026, 4, 4), 500, "From checking", "Erika")])
    ).unwrap()
    return _entry_id(session, "Move to savings"), _entry_id(session, "From checking")


def test_reclassifying_a_fall_through_onto_an_own_account_is_a_transfer(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Checking", cash_rows([statement_row(date(2026, 4, 3), -500, "Move", "Erika")])
    ).unwrap()
    line = _entry_id(session, "Move")
    entries, groups = _state(session)

    assert Reclassify(session).execute(line, "Savings").is_ok

    assert _balances(session) == {"Checking": -500, "Savings": 500, "Unclassified Expense": 0}
    assert _state(session) == (entries + 1, groups + 1)
    row = _classification(session, "Move")
    assert (row.kind, row.corrected, row.final_account.name) == (ClassificationKind.transfer, True, "Savings")


def test_reclassifying_onto_an_own_account_absorbs_the_counterparts_fall_through(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Checking", cash_rows([statement_row(date(2026, 4, 3), -500, "Move", "Erika")])
    ).unwrap()
    ImportStatement(session).execute(
        "Savings", cash_rows([statement_row(date(2026, 4, 4), 500, "From checking", "Erika")])
    ).unwrap()
    transfer = _entry_id(session, "Move")

    Reclassify(session).execute(transfer, "Savings").unwrap()

    assert _balances(session) == {"Checking": -500, "Savings": 500, "Unclassified Expense": 0, "Unclassified Income": 0}
    mirror = _classification(session, "From checking")
    assert (mirror.kind, mirror.mirror_of_entry_id, mirror.corrected) == (ClassificationKind.mirror, transfer, False)
    assert ListUnclassified(session).execute().unwrap() == []


def test_reclassifying_a_people_account_stays_a_category(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    AddAccount(session).execute("People", AccountType.asset).unwrap()
    AddAccount(session).execute("Alice", AccountType.asset, None, "People").unwrap()
    ImportStatement(session).execute(
        "Checking", cash_rows([statement_row(date(2026, 4, 3), -500, "Lent", "Alice")])
    ).unwrap()

    Reclassify(session).execute(_entry_id(session, "Lent"), "Alice").unwrap()

    assert _classification(session, "Lent").kind == ClassificationKind.category


def test_reclassifying_a_transfer_to_a_category_unabsorbs_its_mirror_in_one_group(
    session: Session, cash_rows, statement_row
) -> None:
    transfer, _ = _absorbed(session, cash_rows, statement_row)
    entries, groups = _state(session)

    assert Reclassify(session).execute(transfer, "Gifts").is_ok

    assert _balances(session) == {
        "Checking": -500, "Savings": 500, "Gifts": 500, "Unclassified Income": -500,
    }
    assert _state(session) == (entries + 2, groups + 1)
    moved = _classification(session, "Move to savings")
    assert (moved.kind, moved.corrected, moved.final_account.name) == (ClassificationKind.category, True, "Gifts")
    mirror = _classification(session, "From checking")
    assert (mirror.kind, mirror.mirror_of_entry_id, mirror.corrected) == (ClassificationKind.category, None, False)
    assert mirror.final_account.name == "Unclassified Income"
    assert [u.description for u in ListUnclassified(session).execute().unwrap()] == ["From checking"]


def test_reclassifying_a_transfer_without_a_mirror_to_a_category(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    AddAccount(session).execute("Gifts", AccountType.expense).unwrap()
    ImportStatement(session).execute(
        "Checking",
        cash_rows([statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika", SAVINGS_IBAN)]),
    ).unwrap()
    entries, groups = _state(session)

    Reclassify(session).execute(_entry_id(session, "Move to savings"), "Gifts").unwrap()

    assert _balances(session) == {"Checking": -500, "Savings": 0, "Gifts": 500}
    assert _state(session) == (entries + 1, groups + 1)
    assert _classification(session, "Move to savings").kind == ClassificationKind.category


def test_reclassifying_a_transfer_to_another_own_account_unabsorbs_its_mirror(
    session: Session, cash_rows, statement_row
) -> None:
    transfer, _ = _absorbed(session, cash_rows, statement_row)
    entries, groups = _state(session)

    Reclassify(session).execute(transfer, "Brokerage").unwrap()

    assert _balances(session) == {
        "Checking": -500, "Savings": 500, "Brokerage": 500, "Unclassified Income": -500,
    }
    assert _state(session) == (entries + 2, groups + 1)
    moved = _classification(session, "Move to savings")
    assert (moved.kind, moved.corrected, moved.final_account.name) == (ClassificationKind.transfer, True, "Brokerage")
    assert _classification(session, "From checking").kind == ClassificationKind.category


def test_reclassifying_a_mirror_is_refused(session: Session, cash_rows, statement_row) -> None:
    _, mirror = _absorbed(session, cash_rows, statement_row)
    entries, groups = _state(session)

    for target in ("Gifts", "Brokerage"):
        err = Reclassify(session).execute(mirror, target).unwrap_err()
        assert isinstance(err, IsAMirror)
        assert f"unjoin-transfer {mirror}" in str(err)
    assert _state(session) == (entries, groups)


def test_reclassifying_onto_the_pending_bucket_is_refused(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    AddAccount(session).execute("Pending Remittances", AccountType.asset).unwrap()
    ImportStatement(session).execute(
        "Checking", cash_rows([statement_row(date(2026, 4, 3), -500, "Move", "Erika")])
    ).unwrap()
    entries, groups = _state(session)

    res = Reclassify(session).execute(_entry_id(session, "Move"), "Pending Remittances")

    assert isinstance(res.unwrap_err(), InvalidTransferTarget)
    assert _state(session) == (entries, groups)


def test_reclassifying_onto_the_lines_own_account_is_refused(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Checking", cash_rows([statement_row(date(2026, 4, 3), -500, "Move", "Erika")])
    ).unwrap()
    entries, groups = _state(session)

    res = Reclassify(session).execute(_entry_id(session, "Move"), "Checking")

    err = res.unwrap_err()
    assert isinstance(err, InvalidTransferTarget)
    assert "own account" in str(err)
    assert _state(session) == (entries, groups)


def test_a_fault_while_reclassifying_a_transfer_writes_nothing(
    session: Session, cash_rows, statement_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    transfer, _ = _absorbed(session, cash_rows, statement_row)
    entries, groups = _state(session)
    before = _balances(session)
    monkeypatch.setattr(
        classification_module, "set_classification_outcome_service", lambda *a, **k: Result.err(RuntimeError("boom"))
    )

    assert Reclassify(session).execute(transfer, "Gifts").is_err

    assert _state(session) == (entries, groups)
    assert _balances(session) == before
    assert _classification(session, "From checking").kind == ClassificationKind.mirror


def test_split_line_is_refused_on_a_transfer_and_on_a_mirror(session: Session, cash_rows, statement_row) -> None:
    transfer, mirror = _absorbed(session, cash_rows, statement_row)
    entries, groups = _state(session)

    on_transfer = SplitImportedEntry(session).execute(transfer, Decimal(0), []).unwrap_err()
    on_mirror = SplitImportedEntry(session).execute(mirror, Decimal(0), []).unwrap_err()

    assert isinstance(on_transfer, NotSplittable)
    assert "it is a transfer" in str(on_transfer)
    assert isinstance(on_mirror, NotSplittable)
    assert f"it is the mirror of transfer {transfer}" in str(on_mirror)
    assert _state(session) == (entries, groups)
