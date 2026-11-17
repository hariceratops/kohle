"""Layer 3 — transfer and remittance lifecycle through the CLI (issues 126-136)."""

from datetime import date
from decimal import Decimal

from click.testing import CliRunner
from click.testing import Result as CliResult
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kohle.app.cli.cli import cli
from kohle.domain.models import (
    Account,
    AccountType,
    Classification,
    ClassificationKind,
    JournalEntry,
    JournalLine,
    OperationGroup,
    UnitKind,
)
from kohle.use_cases.accounts import PENDING_REMITTANCES, AddAccount
from kohle.use_cases.journal import ImportStatement
from kohle.use_cases.rules import ApplyRuleFile, PlanRuleFile
from kohle.use_cases.units import AddUnit

SAVINGS_IBAN = "DE44500105175407324931"
RULES = (
    f'[[rule]]\ntransfer = "Savings"\n[rule.when]\niban = "{SAVINGS_IBAN}"\n\n'
    '[[rule]]\nremittance = "IndianBank"\nunit = "INR"\n[rule.when]\ncounterparty = "Fernweh Transfer"\n'
)


def _kohle(session: Session, *args: str) -> CliResult:
    result = CliRunner().invoke(cli, list(args), obj=lambda: session)
    assert result.exit_code == 0, result.output
    return result


def _refused(session: Session, *args: str) -> CliResult:
    result = CliRunner().invoke(cli, list(args), obj=lambda: session)
    assert result.exit_code != 0
    return result


def _entry_id(session: Session, description: str) -> int:
    return session.query(JournalEntry).filter(JournalEntry.description == description).one().id


def _record(session: Session, description: str) -> Classification:
    return session.query(Classification).filter(Classification.journal_entry_id == _entry_id(session, description)).one()


def _balance(session: Session, name: str) -> Decimal:
    account = session.query(Account).filter(Account.name == name).one()
    return sum(
        (line.quantity if line.is_debit else -line.quantity)
        for line in session.query(JournalLine).filter(JournalLine.account_id == account.id)
    ) or Decimal(0)


def _groups(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(OperationGroup))


def _import(session: Session, cash_rows, statement_row, account: str, *rows: dict) -> None:
    ImportStatement(session).execute(account, cash_rows(list(rows))).unwrap()


def test_transfer_and_remittance_lifecycle(session: Session, cash_rows, statement_row) -> None:
    for name in ("Checking", "Savings", "IndianBank", "People"):
        AddAccount(session).execute(name, AccountType.asset).unwrap()
    AddAccount(session).execute("Misc", AccountType.expense).unwrap()
    AddUnit(session).execute("INR", "Indian rupee", UnitKind.currency).unwrap()
    plan = PlanRuleFile(session).execute(RULES).unwrap()
    ApplyRuleFile(session).execute(RULES, plan.base).unwrap()

    # Transfer: the rule moves the money; Savings' own row arrives past the window.
    _import(session, cash_rows, statement_row, "Checking",
            statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika", SAVINGS_IBAN, "m1"))
    _import(session, cash_rows, statement_row, "Savings",
            statement_row(date(2026, 4, 8), 500, "From checking", "Erika", None, "m2"))
    transfer, line = _entry_id(session, "Move to savings"), _entry_id(session, "From checking")
    assert _record(session, "Move to savings").kind is ClassificationKind.transfer
    assert _balance(session, "Savings") == Decimal(1000)
    assert "From checking" in _kohle(session, "list-unclassified").output

    groups = _groups(session)
    _kohle(session, "join-transfer", str(line), str(transfer))
    assert _groups(session) == groups + 1
    assert _balance(session, "Savings") == Decimal(500)
    mirror = _record(session, "From checking")
    assert (mirror.kind, mirror.mirror_of_entry_id, mirror.corrected) == (ClassificationKind.mirror, transfer, True)

    _kohle(session, "unjoin-transfer", str(line))
    assert _balance(session, "Savings") == Decimal(1000)
    row = _record(session, "From checking")
    assert (row.kind, row.mirror_of_entry_id, row.corrected) == (ClassificationKind.category, None, True)

    _kohle(session, "join-transfer", str(line), str(transfer))
    _kohle(session, "reclassify", str(transfer), "Misc")
    assert _balance(session, "Savings") == Decimal(500)  # the mirror went back to its bucket, the move left
    moved = _record(session, "Move to savings")
    assert (moved.kind, moved.corrected, moved.final_account.name) == (ClassificationKind.category, True, "Misc")
    assert _record(session, "From checking").kind is ClassificationKind.category

    # Remittance: euros leave for a rate unknown until the rupees arrive.
    _import(session, cash_rows, statement_row, "Checking",
            statement_row(date(2026, 6, 12), -1012, "Fernweh payment", "Fernweh Transfer", None, "f1"))
    out = _entry_id(session, "Fernweh payment")
    assert _record(session, "Fernweh payment").kind is ClassificationKind.remittance
    assert _balance(session, PENDING_REMITTANCES) == Decimal(1012)
    assert "Fernweh payment" in _kohle(session, "list-pending-remittances").output

    assert "9000 INR for 1012.00 EUR" in _kohle(session, "complete-remittance", str(out), "9000").output
    _kohle(session, "uncomplete-remittance", str(out))
    assert _balance(session, PENDING_REMITTANCES) == Decimal(1012)
    assert _record(session, "Fernweh payment").completion_entry_id is None
    _kohle(session, "complete-remittance", str(out), "90000")
    assert _balance(session, PENDING_REMITTANCES) == Decimal(0)
    assert "No pending remittances" in _kohle(session, "list-pending-remittances").output
    _refused(session, "reclassify", str(out), "Misc")

    # Incoming: the rupees go back out and the gain is realised.
    _import(session, cash_rows, statement_row, "Checking",
            statement_row(date(2026, 6, 20), 1100, "Fernweh refund", "Fernweh Transfer", None, "f2"))
    back = _entry_id(session, "Fernweh refund")
    assert _balance(session, PENDING_REMITTANCES) == Decimal(-1100)
    _kohle(session, "complete-remittance", str(back), "90000")
    assert _balance(session, PENDING_REMITTANCES) == Decimal(0)
    assert _record(session, "Fernweh refund").completion_entry_id is not None
    assert "88.00" in _kohle(session, "realised").output


def test_every_kind_of_move_has_a_distinguishable_record(session: Session, cash_rows, statement_row) -> None:
    for name in ("Checking", "Savings", "IndianBank", "People"):
        AddAccount(session).execute(name, AccountType.asset).unwrap()
    AddAccount(session).execute("Misc", AccountType.expense).unwrap()
    AddUnit(session).execute("INR", "Indian rupee", UnitKind.currency).unwrap()
    plan = PlanRuleFile(session).execute(RULES).unwrap()
    ApplyRuleFile(session).execute(RULES, plan.base).unwrap()
    _import(session, cash_rows, statement_row, "Checking",
            statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika", SAVINGS_IBAN, "m1"),
            statement_row(date(2026, 4, 5), -20, "Coffee", None, None, "c1"),
            statement_row(date(2026, 6, 12), -1012, "Fernweh payment", "Fernweh Transfer", None, "f1"))
    _import(session, cash_rows, statement_row, "Savings",
            statement_row(date(2026, 4, 4), 500, "From checking", "Erika", None, "m2"))
    _import(session, cash_rows, statement_row, "Checking",
            statement_row(date(2026, 6, 20), 1100, "Fernweh refund", "Fernweh Transfer", None, "f2"))
    CliRunner().invoke(cli, ["complete-remittance", str(_entry_id(session, "Fernweh payment")), "90000"], obj=lambda: session)
    CliRunner().invoke(cli, ["complete-remittance", str(_entry_id(session, "Fernweh refund")), "90000"], obj=lambda: session)
    CliRunner().invoke(cli, ["reclassify", str(_entry_id(session, "Coffee")), "Misc"], obj=lambda: session)

    def shape(description: str) -> tuple:
        row = _record(session, description)
        return (row.kind, row.corrected, row.mirror_of_entry_id is not None, row.completion_entry_id is not None)

    shapes = {
        "rule-made transfer": shape("Move to savings"),
        "absorbed mirror": shape("From checking"),
        "completed outgoing remittance": shape("Fernweh payment"),
        "completed incoming remittance": shape("Fernweh refund"),
        "human correction": shape("Coffee"),
    }
    assert shapes["rule-made transfer"] == (ClassificationKind.transfer, False, False, False)
    assert shapes["absorbed mirror"] == (ClassificationKind.mirror, False, True, False)
    assert shapes["human correction"][:2] == (ClassificationKind.category, True)
    assert shapes["completed outgoing remittance"] == shapes["completed incoming remittance"] == (
        ClassificationKind.remittance, False, False, True
    )
    out, back = _record(session, "Fernweh payment"), _record(session, "Fernweh refund")
    assert out.remittance_unit_id == back.remittance_unit_id
    assert out.final_account.name == back.final_account.name == PENDING_REMITTANCES
    outgoing = session.get(JournalEntry, out.journal_entry_id).lines
    incoming = session.get(JournalEntry, back.journal_entry_id).lines
    assert next(line for line in outgoing if line.account.name == PENDING_REMITTANCES).is_debit
    assert not next(line for line in incoming if line.account.name == PENDING_REMITTANCES).is_debit
