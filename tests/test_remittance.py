"""Layer 2 — remittance rules, completion and reversal (issues 132-135). Design §18.5."""

from datetime import date
from decimal import Decimal

import pytest
from click.testing import CliRunner
from sqlalchemy.orm import Session

from kohle.app.cli.cli import cli
from kohle.core.result import Result
from kohle.domain.domain_errors import (
    MalformedRuleFile,
    NotARemittance,
    NotSplittable,
    RemittanceCompleted,
)
from kohle.domain.models import (
    Account,
    AccountType,
    Classification,
    ClassificationKind,
    JournalEntry,
    JournalLine,
    OperationGroup,
    Rule,
    RuleKind,
    UnitKind,
)
from kohle.use_cases import journal as journal_module
from kohle.use_cases.accounts import PENDING_REMITTANCES, AddAccount, own_account
from kohle.use_cases.classification import (
    ApplyClassifyRules,
    ListUnclassified,
    PlanClassifyRules,
    Reclassify,
)
from kohle.use_cases.conditions import Direction
from kohle.use_cases import remittances as remittances_module
from kohle.use_cases.journal import ImportStatement
from kohle.use_cases.lots import QueryRealised
from kohle.use_cases.remittances import CompleteRemittance, ListPendingRemittances
from kohle.use_cases.rules import (
    ApplyRuleFile,
    PlanRuleFile,
    ShowRules,
    parse_rule_file,
)
from kohle.use_cases.splitting import SplitImportedEntry
from kohle.use_cases.units import AddUnit

REMITTANCE_RULE = '[[rule]]\nremittance = "IndianBank"\nunit = "INR"\n[rule.when]\ncounterparty = "Fernweh Transfer"\n'


def _apply(session: Session, text: str) -> Result:
    plan = PlanRuleFile(session).execute(text)
    if plan.is_err:
        return plan
    return ApplyRuleFile(session).execute(text, plan.unwrap().base)


def _ledger(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset)
    AddAccount(session).execute("Savings", AccountType.asset)
    AddAccount(session).execute("IndianBank", AccountType.asset)
    AddUnit(session).execute("INR", "Indian rupee", UnitKind.currency)


def _import(session: Session, cash_rows, statement_row, *rows: tuple, account: str = "Checking") -> None:
    # Named by description: references repeat by position across statements.
    built = [statement_row(*row, None, row[2]) if len(row) == 4 else statement_row(*row, None, None, row[2]) for row in rows]
    ImportStatement(session).execute(account, cash_rows(built)).unwrap()


def _account(session: Session, name: str) -> Account:
    return session.query(Account).filter(Account.name == name).one()


def _balance(session: Session, name: str) -> Decimal:
    account = _account(session, name)
    return sum(
        (line.quantity if line.is_debit else -line.quantity)
        for line in session.query(JournalLine).filter(JournalLine.account_id == account.id)
    ) or Decimal(0)


def _entry_id(session: Session, description: str) -> int:
    return session.query(JournalEntry).filter(JournalEntry.description == description).one().id


OUT = (date(2026, 6, 12), -1012, "Fernweh payment", "Fernweh Transfer")
IN = (date(2026, 6, 20), 1100, "Fernweh refund", "Fernweh Transfer")


# The rule file


def test_a_remittance_rule_round_trips_through_the_rule_file(session: Session) -> None:
    _ledger(session)
    _apply(session, REMITTANCE_RULE + '\n[[rule]]\naccount = "Savings"\n[rule.when]\ndescription = "x"\n').unwrap()

    rule = session.query(Rule).order_by(Rule.id).first()
    assert rule.kind is RuleKind.remittance
    assert rule.account.name == "IndianBank" and rule.unit.identifier == "INR"
    shown = ShowRules(session).execute().unwrap()
    assert 'remittance = "IndianBank"\nunit = "INR"\n' in shown
    assert PlanRuleFile(session).execute(shown).unwrap().is_empty


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('remittance = "IndianBank"\n', "rule 1, unit: is required with remittance"),
        ('account = "IndianBank"\nunit = "INR"\n', "rule 1, unit: is only allowed with remittance"),
        ('transfer = "IndianBank"\nunit = "INR"\n', "rule 1, unit: is only allowed with remittance"),
        ('remittance = "IndianBank"\nunit = ""\n', "rule 1, unit: must be a non-empty string"),
        ('remittance = "IndianBank"\naccount = "Savings"\nunit = "INR"\n', "rule 1, account: cannot be combined with remittance"),
    ],
)
def test_the_rule_file_refuses_a_malformed_remittance_rule(text: str, problem: str) -> None:
    parsed = parse_rule_file(f"[[rule]]\n{text}[rule.when]\ndescription = \"x\"\n")

    assert str(parsed.unwrap_err()) == problem


@pytest.mark.parametrize(
    ("counterpart", "unit", "problem"),
    [
        ("Groceries", "INR", "rule 1, remittance: 'Groceries' is an expense account"),
        ("Pending Remittances", "INR", "rule 1, remittance: 'Pending Remittances' is kohle's pending bucket"),
        ("IndianBank", "INX", "rule 1, unit: no unit named 'INX'"),
        ("IndianBank", "EUR", "rule 1, unit: 'EUR' is not a currency other than EUR"),
        ("IndianBank", "ACME", "rule 1, unit: 'ACME' is not a currency other than EUR"),
    ],
)
def test_applying_refuses_an_invalid_counterpart_or_unit(
    session: Session, counterpart: str, unit: str, problem: str
) -> None:
    _ledger(session)
    AddAccount(session).execute("Groceries", AccountType.expense)
    AddAccount(session).execute(PENDING_REMITTANCES, AccountType.asset)
    AddUnit(session).execute("EUR", "Euro", UnitKind.currency)
    AddUnit(session).execute("ACME", "Acme Corp", UnitKind.security)
    text = f'[[rule]]\nremittance = "{counterpart}"\nunit = "{unit}"\n[rule.when]\ndescription = "x"\n'

    refusal = _apply(session, text).unwrap_err()

    assert isinstance(refusal, MalformedRuleFile)
    assert str(refusal).startswith(problem)
    assert session.query(Rule).count() == 0


def test_a_transfer_rule_refuses_the_pending_bucket_as_its_counterpart(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, REMITTANCE_RULE).unwrap()
    _import(session, cash_rows, statement_row, OUT)
    text = f'[[rule]]\ntransfer = "{PENDING_REMITTANCES}"\n[rule.when]\ndescription = "x"\n'

    refusal = _apply(session, text).unwrap_err()

    assert str(refusal) == f"rule 1, transfer: '{PENDING_REMITTANCES}' is kohle's pending bucket"


def test_the_kind_and_the_unit_are_part_of_a_rules_identity(session: Session) -> None:
    _ledger(session)
    AddUnit(session).execute("NPR", "Nepalese rupee", UnitKind.currency)
    _apply(session, REMITTANCE_RULE).unwrap()
    first = session.query(Rule).one().id

    same = PlanRuleFile(session).execute(ShowRules(session).execute().unwrap()).unwrap()
    other_unit = PlanRuleFile(session).execute(
        REMITTANCE_RULE.replace('"INR"', '"NPR"')
    ).unwrap()
    other_kind = PlanRuleFile(session).execute(
        REMITTANCE_RULE.replace('remittance = "IndianBank"\nunit = "INR"\n', 'transfer = "IndianBank"\n')
    ).unwrap()

    assert same.is_empty
    for changed in (other_unit, other_kind):
        assert [s.rule_id for s in changed.retired] == [first]
        assert len(changed.added) == 1


# The import


def test_the_pending_bucket_is_created_on_the_first_remittance_only(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, REMITTANCE_RULE).unwrap()
    _import(session, cash_rows, statement_row, (date(2026, 6, 1), -5, "Coffee"))
    assert session.query(Account).filter(Account.name == PENDING_REMITTANCES).count() == 0

    _import(session, cash_rows, statement_row, OUT, (date(2026, 6, 13), -3, "Fernweh fee", "Fernweh Transfer"))

    pending = session.query(Account).filter(Account.name == PENDING_REMITTANCES).one()
    assert pending.type is AccountType.asset


def test_an_outgoing_remittance_moves_into_the_pending_bucket_and_is_recorded(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    _apply(session, REMITTANCE_RULE).unwrap()

    _import(session, cash_rows, statement_row, OUT)

    assert _balance(session, "Checking") == Decimal(-1012)
    assert _balance(session, PENDING_REMITTANCES) == Decimal(1012)
    record = session.query(Classification).one()
    assert record.kind is ClassificationKind.remittance
    assert record.final_account.name == PENDING_REMITTANCES
    assert record.remittance_account.name == "IndianBank" and record.remittance_unit.identifier == "INR"
    assert record.completion_entry_id is None and record.mirror_of_entry_id is None
    assert record.corrected is False and record.matched_rule.kind is RuleKind.remittance


def test_an_incoming_remittance_posts_the_pending_bucket_negative(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, REMITTANCE_RULE).unwrap()

    _import(session, cash_rows, statement_row, IN)

    assert _balance(session, "Checking") == Decimal(1100)
    assert _balance(session, PENDING_REMITTANCES) == Decimal(-1100)


def test_a_remittance_rule_never_matches_a_row_imported_into_its_own_counterpart(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    _apply(session, REMITTANCE_RULE).unwrap()

    _import(session, cash_rows, statement_row, (date(2026, 6, 12), 1012, "Fernweh payment", "Fernweh Transfer"), account="IndianBank")

    assert session.query(Account).filter(Account.name == PENDING_REMITTANCES).count() == 0
    assert session.query(Classification).one().kind is ClassificationKind.category


def test_the_euros_in_transit_count_in_net_worth_at_face_value(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, REMITTANCE_RULE).unwrap()
    _import(session, cash_rows, statement_row, (date(2026, 6, 1), 2000, "Salary"), OUT)

    own = [a for a in session.query(Account) if own_account(a, set())]

    assert PENDING_REMITTANCES in [a.name for a in own]
    assert sum(_balance(session, a.name) for a in own) == Decimal(2000)


def test_the_import_is_all_or_nothing_and_one_group(
    session: Session, cash_rows, statement_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ledger(session)
    _apply(session, REMITTANCE_RULE).unwrap()
    groups = session.query(OperationGroup).count()

    _import(session, cash_rows, statement_row, OUT, (date(2026, 6, 13), -3, "Fernweh fee", "Fernweh Transfer"))
    assert session.query(OperationGroup).count() == groups + 1

    entries = session.query(JournalEntry).count()
    real = journal_module.add_classification_service
    calls = []

    def flaky(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            return Result.err(RuntimeError("boom"))
        return real(*args, **kwargs)

    monkeypatch.setattr(journal_module, "add_classification_service", flaky)
    rows = cash_rows([
        statement_row(date(2026, 7, 1), -7, "Fernweh again", "Fernweh Transfer", reference="a"),
        statement_row(date(2026, 7, 2), -8, "Fernweh more", "Fernweh Transfer", reference="b"),
    ])

    assert ImportStatement(session).execute("Checking", rows).is_err
    assert session.query(JournalEntry).count() == entries
    assert session.query(OperationGroup).count() == groups + 1


# The listing


def test_pending_remittances_have_their_own_listing(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, REMITTANCE_RULE).unwrap()
    _import(session, cash_rows, statement_row, OUT, IN, (date(2026, 6, 25), -4, "Coffee"))

    pending = ListPendingRemittances(session).execute().unwrap()

    assert [(p.description, p.direction, p.amount, p.account_name, p.counterpart_name, p.unit_identifier) for p in pending] == [
        ("Fernweh payment", Direction.outgoing, Decimal("1012"), "Checking", "IndianBank", "INR"),
        ("Fernweh refund", Direction.incoming, Decimal("1100"), "Checking", "IndianBank", "INR"),
    ]
    assert [line.description for line in ListUnclassified(session).execute().unwrap()] == ["Coffee"]


def test_nothing_is_listed_before_any_remittance(session: Session) -> None:
    assert ListPendingRemittances(session).execute().unwrap() == []


# classify-rules


def test_classify_rules_applies_remittance_rules_to_fall_through_lines(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _import(session, cash_rows, statement_row, OUT, (date(2026, 6, 13), 3, "Interest"))
    _apply(session, REMITTANCE_RULE).unwrap()

    moves = PlanClassifyRules(session).execute().unwrap()

    assert [(m.description, m.kind, m.account_name, m.unit_identifier) for m in moves] == [
        ("Fernweh payment", ClassificationKind.remittance, "IndianBank", "INR")
    ]
    assert session.query(Account).filter(Account.name == PENDING_REMITTANCES).count() == 0

    ApplyClassifyRules(session).execute(moves).unwrap()

    assert _balance(session, PENDING_REMITTANCES) == Decimal(1012)
    assert _balance(session, "Unclassified Expense") == Decimal(0)
    record = session.query(Classification).join(Classification.entry).filter(JournalEntry.description == "Fernweh payment").one()
    assert record.kind is ClassificationKind.remittance and record.corrected is False
    assert record.rerun_rule_id is not None and record.matched_rule_id is None
    assert record.remittance_account.name == "IndianBank" and record.remittance_unit.identifier == "INR"
    assert [p.description for p in ListPendingRemittances(session).execute().unwrap()] == ["Fernweh payment"]
    assert PlanClassifyRules(session).execute().unwrap() == []


# Corrections


def test_reclassify_reverses_a_pending_remittance(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    AddAccount(session).execute("Fees", AccountType.expense)
    _apply(session, REMITTANCE_RULE).unwrap()
    _import(session, cash_rows, statement_row, OUT)

    Reclassify(session).execute(_entry_id(session, "Fernweh payment"), "Fees").unwrap()

    assert _balance(session, PENDING_REMITTANCES) == Decimal(0)
    assert _balance(session, "Fees") == Decimal(1012)
    record = session.query(Classification).one()
    assert record.kind is ClassificationKind.category and record.corrected is True
    assert record.remittance_account_id is None and record.remittance_unit_id is None
    assert ListPendingRemittances(session).execute().unwrap() == []


def test_split_line_is_refused_on_a_pending_remittance(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, REMITTANCE_RULE).unwrap()
    _import(session, cash_rows, statement_row, OUT)
    entries = session.query(JournalEntry).count()

    refusal = SplitImportedEntry(session).execute(_entry_id(session, "Fernweh payment"), Decimal(0), []).unwrap_err()

    assert isinstance(refusal, NotSplittable) and "it is a remittance" in str(refusal)
    assert session.query(JournalEntry).count() == entries


def test_mirror_recognition_does_not_absorb_into_or_from_a_pending_remittance(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    _apply(
        session,
        REMITTANCE_RULE + '\n[[rule]]\ntransfer = "Checking"\n[rule.when]\ncounterparty = "Own Name"\n',
    ).unwrap()
    # A pending remittance of +500 on Checking, and an own-name row of -500 on
    # Savings that is a transfer into Checking: the opposite amount, in the
    # window, so Checking's remittance would be its mirror if it could be one.
    _import(session, cash_rows, statement_row, (date(2026, 6, 12), 500, "Fernweh refund", "Fernweh Transfer"))
    _import(session, cash_rows, statement_row, (date(2026, 6, 12), -500, "Move", "Own Name"), account="Savings")
    # And a +500 on the counterpart's statement is no mirror of a pending remittance.
    _import(session, cash_rows, statement_row, (date(2026, 6, 13), -500, "Fernweh payment", "Fernweh Transfer"))
    _import(session, cash_rows, statement_row, (date(2026, 6, 13), 500, "Received"), account="IndianBank")

    kinds = {c.entry.description: c.kind for c in session.query(Classification)}
    assert kinds["Fernweh refund"] is ClassificationKind.remittance
    assert kinds["Fernweh payment"] is ClassificationKind.remittance
    assert kinds["Move"] is ClassificationKind.transfer
    assert kinds["Received"] is ClassificationKind.category
    assert session.query(Classification).filter(Classification.mirror_of_entry_id.is_not(None)).count() == 0


# Completion


def _pending_out(session: Session, cash_rows, statement_row) -> int:
    _ledger(session)
    _apply(session, REMITTANCE_RULE).unwrap()
    _import(session, cash_rows, statement_row, OUT)
    return _entry_id(session, "Fernweh payment")


def _currency_lines(session: Session) -> list[JournalLine]:
    return session.query(JournalLine).filter(JournalLine.account_id == _account(session, "IndianBank").id).all()


def test_completing_an_outgoing_remittance_gives_one_lot_of_exactly_x(session: Session, cash_rows, statement_row) -> None:
    entry_id = _pending_out(session, cash_rows, statement_row)
    groups = session.query(OperationGroup).count()

    completed = CompleteRemittance(session).execute(entry_id, Decimal(90000)).unwrap()
    entry = session.get(JournalEntry, completed.completion_entry_id)

    (lot,) = _currency_lines(session)
    assert lot.is_debit and lot.quantity == Decimal(90000) and lot.unit.identifier == "INR"
    assert lot.cost == Decimal("1012.00")
    assert entry.entry_date == OUT[0] and entry.description == "Complete: Fernweh payment"
    assert _balance(session, PENDING_REMITTANCES) == Decimal(0)
    assert ListPendingRemittances(session).execute().unwrap() == []
    assert ListUnclassified(session).execute().unwrap() == []
    record = session.query(Classification).one()
    assert record.kind is ClassificationKind.remittance and record.completion_entry_id == entry.id
    assert session.query(OperationGroup).count() == groups + 1


def test_the_lot_is_dated_the_day_the_euros_left_whatever_the_recording_order(
    session: Session, cash_rows, statement_row
) -> None:
    entry_id = _pending_out(session, cash_rows, statement_row)
    AddAccount(session).execute("People", AccountType.asset)
    runner = CliRunner()
    for args in (
        ["record", "2026-06-15", "Remittance", "100000", "--from", "Checking", "--to", "IndianBank", "--to-unit", "INR", "--total", "1100"],
        ["record", "2026-06-20", "Back", "40000", "--from", "IndianBank", "--to", "Checking", "--from-unit", "INR", "--total", "500"],
    ):
        assert runner.invoke(cli, args, obj=lambda: session).exit_code == 0

    CompleteRemittance(session).execute(entry_id, Decimal(90000)).unwrap()

    (sale,) = QueryRealised(session).execute(None).unwrap()
    assert abs(sale.fifo_cost - Decimal(1012) * 40000 / 90000) < Decimal("0.0001")


@pytest.mark.parametrize("amount", ["0", "-5"])
def test_complete_remittance_refuses_an_amount_not_above_zero(session: Session, cash_rows, statement_row, amount: str) -> None:
    entry_id = _pending_out(session, cash_rows, statement_row)

    result = CliRunner().invoke(cli, ["complete-remittance", str(entry_id), amount], obj=lambda: session)

    assert result.exit_code == 2
    assert _currency_lines(session) == []


def test_the_command_reports_the_currency_and_the_euros(session: Session, cash_rows, statement_row) -> None:
    entry_id = _pending_out(session, cash_rows, statement_row)

    result = CliRunner().invoke(cli, ["complete-remittance", str(entry_id), "90000"], obj=lambda: session)

    assert result.exit_code == 0, result.output
    assert result.output.strip() == f"Completed remittance {entry_id}: 90000 INR for 1012.00 EUR"


def test_completing_twice_or_a_non_remittance_fails_and_writes_nothing(session: Session, cash_rows, statement_row) -> None:
    entry_id = _pending_out(session, cash_rows, statement_row)
    _import(session, cash_rows, statement_row, (date(2026, 6, 1), -5, "Coffee"))
    first = CompleteRemittance(session).execute(entry_id, Decimal(90000)).unwrap().completion_entry_id
    entries, groups = session.query(JournalEntry).count(), session.query(OperationGroup).count()

    again = CompleteRemittance(session).execute(entry_id, Decimal(80000)).unwrap_err()
    coffee = CompleteRemittance(session).execute(_entry_id(session, "Coffee"), Decimal(1)).unwrap_err()

    assert isinstance(again, RemittanceCompleted) and again.completion_entry_id == first
    assert "uncomplete-remittance" in str(again)
    assert isinstance(coffee, NotARemittance)
    assert session.query(JournalEntry).count() == entries
    assert session.query(OperationGroup).count() == groups


def test_completion_is_all_or_nothing(session: Session, cash_rows, statement_row, monkeypatch: pytest.MonkeyPatch) -> None:
    entry_id = _pending_out(session, cash_rows, statement_row)
    entries, groups = session.query(JournalEntry).count(), session.query(OperationGroup).count()
    monkeypatch.setattr(remittances_module, "set_completion_service", lambda *a, **k: Result.err(RuntimeError("boom")))

    assert CompleteRemittance(session).execute(entry_id, Decimal(90000)).is_err

    assert session.query(JournalEntry).count() == entries
    assert session.query(OperationGroup).count() == groups
    assert session.query(Classification).one().completion_entry_id is None


def test_reclassify_and_split_line_refuse_a_completed_remittance(session: Session, cash_rows, statement_row) -> None:
    entry_id = _pending_out(session, cash_rows, statement_row)
    AddAccount(session).execute("Fees", AccountType.expense)
    CompleteRemittance(session).execute(entry_id, Decimal(90000)).unwrap()
    entries = session.query(JournalEntry).count()

    reclassified = Reclassify(session).execute(entry_id, "Fees").unwrap_err()
    split = SplitImportedEntry(session).execute(entry_id, Decimal(0), []).unwrap_err()

    assert isinstance(reclassified, RemittanceCompleted)
    assert str(reclassified).endswith(f"uncomplete-remittance {entry_id} first")
    assert isinstance(split, NotSplittable) and "it is a remittance" in str(split)
    assert session.query(JournalEntry).count() == entries


def _lot_of_90000_for_1012(session: Session, cash_rows, statement_row) -> None:
    out_id = _pending_out(session, cash_rows, statement_row)
    CompleteRemittance(session).execute(out_id, Decimal(90000)).unwrap()


def _pending_in(session: Session, cash_rows, statement_row) -> int:
    _lot_of_90000_for_1012(session, cash_rows, statement_row)
    AddAccount(session).execute("People", AccountType.asset)  # realised reads the People subtree
    _import(session, cash_rows, statement_row, IN)
    return _entry_id(session, "Fernweh refund")


def test_completing_an_incoming_remittance_consumes_the_lot_and_realises_the_gain(
    session: Session, cash_rows, statement_row
) -> None:
    entry_id = _pending_in(session, cash_rows, statement_row)
    groups = session.query(OperationGroup).count()

    completed = CompleteRemittance(session).execute(entry_id, Decimal(90000)).unwrap()
    entry = session.get(JournalEntry, completed.completion_entry_id)

    credit, debit = sorted(entry.lines, key=lambda line: line.is_debit)
    assert credit.account.name == "IndianBank" and credit.unit.identifier == "INR"
    assert credit.quantity == Decimal(90000) and credit.cost == Decimal("1100.00")
    assert debit.account.name == PENDING_REMITTANCES and debit.quantity == Decimal("1100.00")
    assert entry.entry_date == IN[0] and entry.description == "Complete: Fernweh refund"
    assert _balance(session, PENDING_REMITTANCES) == Decimal(0)
    assert ListPendingRemittances(session).execute().unwrap() == []
    record = session.query(Classification).filter(Classification.journal_entry_id == entry_id).one()
    assert record.completion_entry_id == entry.id
    assert session.query(OperationGroup).count() == groups + 1
    (sale,) = QueryRealised(session).execute(None).unwrap()
    assert (sale.account_name, sale.unit_identifier, sale.quantity) == ("IndianBank", "INR", Decimal(90000))
    assert sale.proceeds == Decimal("1100.00") and sale.fifo_cost == Decimal("1012.00")
    assert sale.gain == Decimal("88.00")


def test_an_incoming_remittance_is_pending_with_the_unit_still_on_the_counterpart(
    session: Session, cash_rows, statement_row
) -> None:
    _pending_in(session, cash_rows, statement_row)

    (pending,) = ListPendingRemittances(session).execute().unwrap()

    assert (pending.direction, pending.amount, pending.counterpart_name, pending.unit_identifier) == (
        Direction.incoming,
        Decimal(1100),
        "IndianBank",
        "INR",
    )
    assert _balance(session, "Checking") == Decimal(-1012) + Decimal(1100)
    assert _balance(session, PENDING_REMITTANCES) == Decimal(-1100)
    assert QueryRealised(session).execute(None).unwrap() == []


def test_a_direction_condition_restricts_a_remittance_rule_to_inflows(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, REMITTANCE_RULE.replace("counterparty", 'direction = "in"\ncounterparty')).unwrap()

    _import(session, cash_rows, statement_row, OUT, IN)

    kinds = {c.entry.description: c.kind for c in session.query(Classification)}
    assert kinds == {"Fernweh payment": ClassificationKind.category, "Fernweh refund": ClassificationKind.remittance}


def test_an_incoming_completion_larger_than_the_lots_fails_and_writes_nothing(
    session: Session, cash_rows, statement_row
) -> None:
    entry_id = _pending_in(session, cash_rows, statement_row)
    entries, groups = session.query(JournalEntry).count(), session.query(OperationGroup).count()
    lines = session.query(JournalLine).count()

    refusal = CompleteRemittance(session).execute(entry_id, Decimal(90001))

    assert refusal.is_err
    assert session.query(JournalEntry).count() == entries
    assert session.query(JournalLine).count() == lines
    assert session.query(OperationGroup).count() == groups
    record = session.query(Classification).filter(Classification.journal_entry_id == entry_id).one()
    assert record.completion_entry_id is None
    assert [p.description for p in ListPendingRemittances(session).execute().unwrap()] == ["Fernweh refund"]


def test_an_incoming_completion_without_any_lot_fails_and_writes_nothing(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, REMITTANCE_RULE).unwrap()
    _import(session, cash_rows, statement_row, IN)
    entries = session.query(JournalEntry).count()

    assert CompleteRemittance(session).execute(_entry_id(session, "Fernweh refund"), Decimal(5)).is_err
    assert session.query(JournalEntry).count() == entries


@pytest.mark.skip(reason="scaffold")
def test_uncomplete_remittance() -> None:
    # TODO (135): uncomplete-remittance both directions, reversal and lot restoration, migration c
    ...
