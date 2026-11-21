"""Layer 2 — import-statement end to end for transfers (issues 126-128). Design §18.2-18.3."""

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.domain_errors import ClassifyPlanChanged
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
)
from kohle.use_cases import journal as journal_module
from kohle.use_cases import transfers as transfers_module
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.classification import (
    ApplyClassifyRules,
    ListUnclassified,
    PlanClassifyRules,
)
from kohle.use_cases.journal import ImportStatement
from kohle.use_cases.rules import ApplyRuleFile, PlanRuleFile, ShowRules

SAVINGS_IBAN = "DE44500105175407324931"
BUCKETS = ("Unclassified Expense", "Unclassified Income")


def _apply(session: Session, text: str) -> Result:
    plan = PlanRuleFile(session).execute(text)
    if plan.is_err:
        return plan
    return ApplyRuleFile(session).execute(text, plan.unwrap().base)


def _transfer_rule(account: str, iban: str = SAVINGS_IBAN) -> str:
    return f'[[rule]]\ntransfer = "{account}"\n[rule.when]\niban = "{iban}"\n'


def _ledger(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset)
    AddAccount(session).execute("Savings", AccountType.asset)
    AddAccount(session).execute("Groceries", AccountType.expense)


def _balances(session: Session) -> dict[str, int]:
    from kohle.domain.models import Account, JournalLine

    rows = session.execute(
        select(Account.name, func.sum(JournalLine.quantity * func.iif(JournalLine.is_debit, 1, -1)))
        .join(JournalLine, JournalLine.account_id == Account.id)
        .group_by(Account.name)
    ).all()
    return {name: int(total) for name, total in rows}


def test_a_transfer_rule_posts_one_move_between_the_two_accounts(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings")).unwrap()
    rows = cash_rows([statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika Beispiel", SAVINGS_IBAN)])

    assert ImportStatement(session).execute("Checking", rows).unwrap() == 1

    assert session.query(JournalEntry).count() == 1
    assert _balances(session) == {"Checking": -500, "Savings": 500}
    assert not any(name in _balances(session) for name in (*BUCKETS, "Groceries"))


def test_the_classification_tells_a_rule_made_transfer_apart(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings") + '\n[[rule]]\naccount = "Groceries"\n[rule.when]\ndescription = "aldi"\n').unwrap()
    rows = cash_rows([
        statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika Beispiel", SAVINGS_IBAN),
        statement_row(date(2026, 4, 4), -20, "ALDI", "ALDI SUED"),
        statement_row(date(2026, 4, 5), -7, "Coffee"),
    ])

    ImportStatement(session).execute("Checking", rows).unwrap()

    by_description = {
        c.entry.description: c
        for c in session.query(Classification).all()
    }
    transfer = by_description["Move to savings"]
    assert transfer.kind is ClassificationKind.transfer
    assert transfer.corrected is False and transfer.mirror_of_entry_id is None
    assert transfer.matched_rule is not None and transfer.matched_rule.kind is RuleKind.transfer
    assert transfer.final_account.name == "Savings"
    assert transfer.proposed_account_id == transfer.final_account_id
    assert by_description["ALDI"].kind is ClassificationKind.category
    assert by_description["Coffee"].kind is ClassificationKind.category


def test_an_account_rule_onto_an_asset_clearing_account_keeps_its_meaning(
    session: Session, cash_rows, statement_row
) -> None:
    AddAccount(session).execute("Checking", AccountType.asset)
    AddAccount(session).execute("Transfers", AccountType.asset)
    _apply(session, f'[[rule]]\naccount = "Transfers"\n[rule.when]\niban = "{SAVINGS_IBAN}"\n').unwrap()
    rows = cash_rows([statement_row(date(2026, 4, 3), -500, "Move", "Erika Beispiel", SAVINGS_IBAN)])

    ImportStatement(session).execute("Checking", rows).unwrap()

    assert session.query(Rule).one().kind is RuleKind.category
    assert session.query(Classification).one().kind is ClassificationKind.category


def test_the_import_is_one_audit_trail_group(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings")).unwrap()
    before = session.query(OperationGroup).count()
    rows = cash_rows([
        statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika Beispiel", SAVINGS_IBAN),
        statement_row(date(2026, 4, 4), -20, "ALDI"),
    ])

    ImportStatement(session).execute("Checking", rows).unwrap()

    assert session.query(OperationGroup).count() == before + 1


def test_a_fault_part_way_leaves_nothing_written_and_no_group(
    session: Session, cash_rows, statement_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings")).unwrap()
    entries = session.query(JournalEntry).count()
    groups = session.query(OperationGroup).count()
    real = journal_module.add_classification_service
    calls = []

    def flaky(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            return Result.err(RuntimeError("boom"))
        return real(*args, **kwargs)

    monkeypatch.setattr(journal_module, "add_classification_service", flaky)
    rows = cash_rows([
        statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika Beispiel", SAVINGS_IBAN),
        statement_row(date(2026, 4, 4), -20, "ALDI"),
    ])

    assert ImportStatement(session).execute("Checking", rows).is_err

    assert session.query(JournalEntry).count() == entries
    assert session.query(OperationGroup).count() == groups
    assert session.query(Classification).count() == 0


def test_a_transfer_rule_never_matches_a_row_imported_into_its_own_counterpart(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    text = _transfer_rule("Savings") + '\n[[rule]]\naccount = "Groceries"\n[rule.when]\niban = "' + SAVINGS_IBAN + '"\n'
    _apply(session, text).unwrap()
    rows = cash_rows([statement_row(date(2026, 4, 4), 500, "Move to savings", "Erika Beispiel", SAVINGS_IBAN)])

    ImportStatement(session).execute("Savings", rows).unwrap()

    classification = session.query(Classification).one()
    assert classification.kind is ClassificationKind.category
    assert classification.final_account.name == "Groceries"


def test_the_row_falls_to_its_bucket_when_only_the_skipped_rule_matches(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings")).unwrap()
    rows = cash_rows([statement_row(date(2026, 4, 4), 500, "Move to savings", "Erika Beispiel", SAVINGS_IBAN)])

    ImportStatement(session).execute("Savings", rows).unwrap()

    classification = session.query(Classification).one()
    assert classification.final_account.name == "Unclassified Income"
    assert classification.matched_rule_id is None


def test_a_leaf_asset_or_liability_counterpart_is_accepted(session: Session) -> None:
    AddAccount(session).execute("Card", AccountType.liability)
    AddAccount(session).execute("Cash", AccountType.asset)
    text = _transfer_rule("Card") + "\n" + _transfer_rule("Cash", "DE02120300000000202051")

    assert _apply(session, text).is_ok
    assert [r.kind for r in session.query(Rule).order_by(Rule.id)] == [RuleKind.transfer, RuleKind.transfer]


@pytest.mark.parametrize(
    ("account", "message"),
    [
        ("Groceries", "rule 1, transfer: 'Groceries' is an expense account; a transfer's counterpart must be an own asset or liability account"),
        ("Salary", "rule 1, transfer: 'Salary' is an income account; a transfer's counterpart must be an own asset or liability account"),
        ("Unclassified Expense", "rule 1, transfer: 'Unclassified Expense' is an expense account"),
        ("Unclassified Income", "rule 1, transfer: 'Unclassified Income' is an income account"),
        ("Alice", "rule 1, transfer: 'Alice' is a People account; money to or from a person stays with split-line"),
    ],
)
def test_a_counterpart_that_is_not_an_own_account_is_refused_naming_the_rule(
    session: Session, people_root, account: str, message: str
) -> None:
    AddAccount(session).execute("Groceries", AccountType.expense)
    AddAccount(session).execute("Salary", AccountType.income)
    AddAccount(session).execute("Unclassified Expense", AccountType.expense)
    AddAccount(session).execute("Unclassified Income", AccountType.income)
    AddAccount(session).execute("Alice", AccountType.asset, parent_name="People")

    result = _apply(session, _transfer_rule(account))

    assert result.is_err and str(result.unwrap_err()).startswith(message)
    assert session.query(Rule).count() == 0


def test_a_missing_or_non_leaf_counterpart_is_refused_under_the_transfer_key(session: Session) -> None:
    AddAccount(session).execute("Savings", AccountType.asset)
    AddAccount(session).execute("Holiday", AccountType.asset, parent_name="Savings")

    assert str(_apply(session, _transfer_rule("Nowhere")).unwrap_err()) == "rule 1, transfer: no account named 'Nowhere'"
    assert "rule 1, transfer: 'Savings' has sub-accounts" in str(_apply(session, _transfer_rule("Savings")).unwrap_err())


def test_the_kind_is_part_of_the_identity_so_changing_it_retires_the_rule(session: Session) -> None:
    _ledger(session)
    _apply(session, f'[[rule]]\naccount = "Savings"\n[rule.when]\niban = "{SAVINGS_IBAN}"\n').unwrap()

    plan = _apply(session, _transfer_rule("Savings")).unwrap()

    assert (len(plan.added), len(plan.retired)) == (1, 1)
    kinds = [(r.kind, r.deleted_at is None) for r in session.query(Rule).order_by(Rule.id)]
    assert kinds == [(RuleKind.category, False), (RuleKind.transfer, True)]
    assert 'transfer = "Savings"' in ShowRules(session).execute().unwrap()


def test_a_ledger_without_transfer_rules_imports_as_before(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    rows = cash_rows([statement_row(date(2026, 4, 3), -500, "Move", "Erika Beispiel", SAVINGS_IBAN)])

    ImportStatement(session).execute("Checking", rows).unwrap()

    assert _balances(session) == {"Checking": -500, "Unclassified Expense": 500}
    assert session.query(Classification).one().kind is ClassificationKind.category


CHECKING_IBAN = "DE02120300000000202051"
MOVE_RULES = _transfer_rule("Savings", SAVINGS_IBAN) + "\n" + _transfer_rule("Checking", CHECKING_IBAN)


def _out(statement_row, day: date = date(2026, 4, 3), amount: float = -500, **kwargs) -> dict:
    return statement_row(day, amount, "Move to savings", "Erika Beispiel", kwargs.pop("iban", SAVINGS_IBAN), **kwargs)


def _in(statement_row, day: date = date(2026, 4, 4), amount: float = 500, **kwargs) -> dict:
    return statement_row(day, amount, "Move from checking", "Erika Beispiel", kwargs.pop("iban", CHECKING_IBAN), **kwargs)


def _unclassified(session: Session) -> list:
    return ListUnclassified(session).execute().unwrap()


def _by_kind(session: Session, kind: ClassificationKind) -> list[Classification]:
    return session.query(Classification).filter(Classification.kind == kind).order_by(Classification.id).all()


@pytest.mark.parametrize(("checking_first", "move_day"), [(True, date(2026, 4, 3)), (False, date(2026, 4, 4))])
def test_the_transfer_counts_once_whichever_statement_arrives_first(
    session: Session, cash_rows, statement_row, checking_first: bool, move_day: date
) -> None:
    _ledger(session)
    _apply(session, MOVE_RULES).unwrap()
    checking = cash_rows([_out(statement_row)])
    savings = cash_rows([_in(statement_row)])

    order = [("Checking", checking), ("Savings", savings)]
    for account, rows in order if checking_first else reversed(order):
        assert ImportStatement(session).execute(account, rows).unwrap() == 1

    balances = _balances(session)
    assert (balances["Checking"], balances["Savings"]) == (-500, 500)
    assert all(total == 0 for name, total in balances.items() if name not in ("Checking", "Savings"))
    assert _unclassified(session) == []
    transfer = _by_kind(session, ClassificationKind.transfer)
    assert len(transfer) == 1 and transfer[0].entry.entry_date == move_day
    assert transfer[0].final_account.name == ("Savings" if checking_first else "Checking")
    assert len(_by_kind(session, ClassificationKind.mirror)) == 1


def test_re_importing_either_statement_writes_nothing(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, MOVE_RULES).unwrap()
    checking, savings = cash_rows([_out(statement_row)]), cash_rows([_in(statement_row)])
    ImportStatement(session).execute("Checking", checking).unwrap()
    ImportStatement(session).execute("Savings", savings).unwrap()
    entries, groups = session.query(JournalEntry).count(), session.query(OperationGroup).count()

    assert ImportStatement(session).execute("Savings", savings).unwrap() == 0
    assert ImportStatement(session).execute("Checking", checking).unwrap() == 0

    assert session.query(JournalEntry).count() == entries
    assert session.query(OperationGroup).count() == groups


def test_the_absorbed_row_has_its_own_record_naming_the_move_it_joined(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    _apply(session, MOVE_RULES).unwrap()
    ImportStatement(session).execute("Checking", cash_rows([_out(statement_row)])).unwrap()
    ImportStatement(session).execute("Savings", cash_rows([_in(statement_row)])).unwrap()

    transfer = _by_kind(session, ClassificationKind.transfer)[0]
    mirror = _by_kind(session, ClassificationKind.mirror)[0]

    assert mirror.mirror_of_entry_id == transfer.journal_entry_id
    assert mirror.journal_entry_id != transfer.journal_entry_id
    assert mirror.proposed_account_id == session.query(Account).filter_by(name="Unclassified Income").one().id
    assert mirror.final_account.name == "Savings"
    assert mirror.matched_rule_id is None
    assert not mirror.corrected


def test_the_absorbed_row_leaves_a_net_zero_pair_beside_the_move(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, MOVE_RULES).unwrap()
    ImportStatement(session).execute("Checking", cash_rows([_out(statement_row)])).unwrap()
    ImportStatement(session).execute("Savings", cash_rows([_in(statement_row)])).unwrap()

    mirror = _by_kind(session, ClassificationKind.mirror)[0]
    savings = session.query(Account).filter_by(name="Savings").one()
    lines = session.query(JournalLine).filter(JournalLine.account_id == savings.id).all()
    own = [line for line in lines if line.entry_id != _by_kind(session, ClassificationKind.transfer)[0].journal_entry_id]

    assert len(own) == 2
    assert sorted(line.is_debit for line in own) == [False, True]
    assert {line.value for line in own} == {500}
    assert mirror.entry.entry_date == date(2026, 4, 4)
    assert session.query(JournalEntry).count() == 3


def test_a_rule_cannot_classify_a_mirror(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings") + '\n[[rule]]\naccount = "Groceries"\n[rule.when]\ndescription = "Move"\n').unwrap()
    ImportStatement(session).execute("Checking", cash_rows([_out(statement_row)])).unwrap()
    ImportStatement(session).execute("Savings", cash_rows([_in(statement_row)])).unwrap()

    mirror = _by_kind(session, ClassificationKind.mirror)[0]

    assert mirror.matched_rule_id is None
    assert "Groceries" not in _balances(session)


def test_a_fall_through_that_was_imported_first_is_cancelled_when_the_move_posts(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings", SAVINGS_IBAN)).unwrap()
    ImportStatement(session).execute("Savings", cash_rows([_in(statement_row)])).unwrap()
    assert len(_unclassified(session)) == 1
    groups = session.query(OperationGroup).count()

    ImportStatement(session).execute("Checking", cash_rows([_out(statement_row)])).unwrap()

    assert session.query(OperationGroup).count() == groups + 1
    assert _unclassified(session) == []
    balances = _balances(session)
    assert (balances["Checking"], balances["Savings"]) == (-500, 500)
    assert balances["Unclassified Income"] == 0
    transfer = _by_kind(session, ClassificationKind.transfer)[0]
    mirror = _by_kind(session, ClassificationKind.mirror)[0]
    assert transfer.entry.entry_date == date(2026, 4, 3)
    assert mirror.mirror_of_entry_id == transfer.journal_entry_id
    assert not mirror.corrected


@pytest.mark.parametrize(("days", "absorbed"), [(3, True), (4, False)])
def test_the_window_is_three_days_after_the_transfer(
    session: Session, cash_rows, statement_row, days: int, absorbed: bool
) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings")).unwrap()
    ImportStatement(session).execute("Checking", cash_rows([_out(statement_row)])).unwrap()

    late = _in(statement_row, day=date(2026, 4, 3) + timedelta(days=days))
    ImportStatement(session).execute("Savings", cash_rows([late])).unwrap()

    assert (len(_by_kind(session, ClassificationKind.mirror)) == 1) is absorbed
    assert (len(_unclassified(session)) == 0) is absorbed
    assert _balances(session)["Savings"] == (500 if absorbed else 1000)


def test_a_known_source_iban_must_match_the_rows_counterparty(session: Session, cash_rows, statement_row) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, CHECKING_IBAN)
    AddAccount(session).execute("Savings", AccountType.asset)
    _apply(session, _transfer_rule("Savings")).unwrap()
    ImportStatement(session).execute("Checking", cash_rows([_out(statement_row)])).unwrap()

    stranger = _in(statement_row, iban="DE89370400440532013000", reference="other")
    ImportStatement(session).execute("Savings", cash_rows([stranger])).unwrap()
    assert _by_kind(session, ClassificationKind.mirror) == []
    assert len(_unclassified(session)) == 1

    spaced = _in(statement_row, iban="de02 1203 0000 0000 2020 51", reference="mine", amount=500)
    ImportStatement(session).execute("Savings", cash_rows([spaced])).unwrap()
    assert len(_by_kind(session, ClassificationKind.mirror)) == 1


def test_rows_pair_with_the_nearest_transfer_and_a_transfer_pairs_only_once(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings")).unwrap()
    ImportStatement(session).execute(
        "Checking",
        cash_rows([_out(statement_row, day=date(2026, 4, 1)), _out(statement_row, day=date(2026, 4, 4))]),
    ).unwrap()
    early, late = _by_kind(session, ClassificationKind.transfer)

    rows = [_in(statement_row, day=date(2026, 4, 3)), _in(statement_row, day=date(2026, 4, 3)), _in(statement_row, day=date(2026, 4, 3))]
    ImportStatement(session).execute("Savings", cash_rows(rows)).unwrap()

    mirrors = _by_kind(session, ClassificationKind.mirror)
    assert [m.mirror_of_entry_id for m in mirrors] == [late.journal_entry_id, early.journal_entry_id]
    assert len(_unclassified(session)) == 1


def test_a_counterpart_that_was_never_imported_leaves_one_move(session: Session, cash_rows, statement_row) -> None:
    AddAccount(session).execute("Checking", AccountType.asset)
    AddAccount(session).execute("Cash", AccountType.asset)
    _apply(session, _transfer_rule("Cash", SAVINGS_IBAN)).unwrap()

    ImportStatement(session).execute("Checking", cash_rows([_out(statement_row)])).unwrap()

    assert _balances(session) == {"Checking": -500, "Cash": 500}
    assert _unclassified(session) == []


def test_a_fault_while_absorbing_leaves_nothing_written_and_no_group(
    session: Session, cash_rows, statement_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ledger(session)
    _apply(session, MOVE_RULES).unwrap()
    ImportStatement(session).execute("Checking", cash_rows([_out(statement_row)])).unwrap()
    entries, groups = session.query(JournalEntry).count(), session.query(OperationGroup).count()
    classifications = session.query(Classification).count()
    monkeypatch.setattr(transfers_module, "set_mirror_service", lambda *args, **kwargs: Result.err(RuntimeError("boom")))

    assert ImportStatement(session).execute("Savings", cash_rows([_in(statement_row)])).is_err

    assert session.query(JournalEntry).count() == entries
    assert session.query(OperationGroup).count() == groups
    assert session.query(Classification).count() == classifications


# classify-rules (issue 128, design §6, §18.3)


def _import_unruled(session: Session, cash_rows, statement_row, *, out_rows=None, in_rows=None) -> None:
    """Both statements imported before any rule exists, so every row is a fall-through."""
    _ledger(session)
    ImportStatement(session).execute("Checking", cash_rows(out_rows or [_out(statement_row)])).unwrap()
    ImportStatement(session).execute("Savings", cash_rows(in_rows or [_in(statement_row)])).unwrap()


def _classify(session: Session) -> list:
    moves = PlanClassifyRules(session).execute().unwrap()
    return ApplyClassifyRules(session).execute(moves).unwrap()


def test_classify_rules_moves_a_transfer_and_absorbs_its_mirror_in_one_run(
    session: Session, cash_rows, statement_row
) -> None:
    _import_unruled(session, cash_rows, statement_row)
    _apply(session, _transfer_rule("Savings")).unwrap()
    groups = session.query(OperationGroup).count()

    moves = PlanClassifyRules(session).execute().unwrap()

    assert [(m.kind, m.rule_id is None, m.account_name) for m in moves] == [
        (ClassificationKind.transfer, False, "Savings"),
        (ClassificationKind.mirror, True, "Savings"),
    ]
    assert moves[1].mirror_of == moves[0].entry_id
    assert ApplyClassifyRules(session).execute(moves).unwrap() == moves

    assert session.query(OperationGroup).count() == groups + 1
    balances = _balances(session)
    assert (balances["Checking"], balances["Savings"]) == (-500, 500)
    assert balances["Unclassified Expense"] == 0 and balances["Unclassified Income"] == 0
    assert _unclassified(session) == []
    transfer = _by_kind(session, ClassificationKind.transfer)[0]
    mirror = _by_kind(session, ClassificationKind.mirror)[0]
    assert transfer.rerun_rule_id is not None and not transfer.corrected
    assert transfer.matched_rule_id is None and transfer.final_account.name == "Savings"
    assert mirror.mirror_of_entry_id == transfer.journal_entry_id
    assert mirror.rerun_rule_id is None and not mirror.corrected


def test_the_preview_shows_both_lines_with_a_kind_column(session: Session, cash_rows, statement_row) -> None:
    from click.testing import CliRunner

    from kohle.app.cli.cli import cli

    _import_unruled(session, cash_rows, statement_row)
    _apply(session, _transfer_rule("Savings")).unwrap()
    out_id = _by_kind(session, ClassificationKind.category)[0].journal_entry_id

    result = CliRunner().invoke(cli, ["classify-rules"], obj=lambda: session, input="n\n")

    lines = result.output.splitlines()
    assert lines[0].split() == ["entry_id", "date", "description", "amount", "from", "to", "rule", "kind"]
    assert lines[2].split()[-1] == "transfer"
    assert " ".join(lines[3].split()[-4:]) == f"- mirror of {out_id}"
    assert "Move 2 line(s)?" in result.output


def test_a_mirror_matched_by_a_category_rule_is_absorbed_not_moved(session: Session, cash_rows, statement_row) -> None:
    _import_unruled(session, cash_rows, statement_row)
    text = _transfer_rule("Savings") + '\n[[rule]]\naccount = "Groceries"\n[rule.when]\ndescription = "Move"\n'
    _apply(session, text).unwrap()

    moves = _classify(session)

    assert [m.kind for m in moves] == [ClassificationKind.transfer, ClassificationKind.mirror]
    assert "Groceries" not in _balances(session)


def test_a_fall_through_that_mirrors_an_existing_transfer_is_absorbed_before_any_rule(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings")).unwrap()
    ImportStatement(session).execute("Checking", cash_rows([_out(statement_row)])).unwrap()
    # Outside the window at import, so it fell through; brought inside it here
    # to stand for a row the import's pairing missed.
    ImportStatement(session).execute("Savings", cash_rows([_in(statement_row, day=date(2026, 4, 9))])).unwrap()
    row = _by_kind(session, ClassificationKind.category)[0]
    row.entry.entry_date = date(2026, 4, 4)
    session.commit()
    _apply(session, _transfer_rule("Savings") + '\n[[rule]]\naccount = "Groceries"\n[rule.when]\ndescription = "Move"\n').unwrap()

    moves = _classify(session)

    assert [m.kind for m in moves] == [ClassificationKind.mirror]
    assert moves[0].rule_id is None
    assert "Groceries" not in _balances(session)


def test_symmetric_transfer_rules_let_the_earlier_line_make_the_move(
    session: Session, cash_rows, statement_row
) -> None:
    _import_unruled(session, cash_rows, statement_row)
    _apply(session, MOVE_RULES).unwrap()

    moves = _classify(session)

    assert [m.kind for m in moves] == [ClassificationKind.transfer, ClassificationKind.mirror]
    transfer = _by_kind(session, ClassificationKind.transfer)[0]
    assert transfer.entry.entry_date == date(2026, 4, 3) and transfer.final_account.name == "Savings"
    assert _unclassified(session) == []


def test_classify_rules_leaves_rule_classified_and_human_touched_lines_alone(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    ImportStatement(session).execute("Checking", cash_rows([_out(statement_row)])).unwrap()
    ImportStatement(session).execute("Savings", cash_rows([_in(statement_row)])).unwrap()
    savings_row = _by_kind(session, ClassificationKind.category)[1]
    savings_row.corrected = True
    savings_row_id = savings_row.id
    session.commit()
    _apply(session, _transfer_rule("Savings")).unwrap()

    moves = PlanClassifyRules(session).execute().unwrap()

    assert [m.kind for m in moves] == [ClassificationKind.transfer]
    _classify(session)
    assert session.get(Classification, savings_row_id).final_account.name == "Unclassified Income"
    assert _by_kind(session, ClassificationKind.mirror) == []


def test_a_transfer_with_no_mirror_candidate_is_a_single_move(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    ImportStatement(session).execute("Checking", cash_rows([_out(statement_row)])).unwrap()
    _apply(session, _transfer_rule("Savings")).unwrap()

    moves = _classify(session)

    assert [m.kind for m in moves] == [ClassificationKind.transfer]
    assert _balances(session) == {"Checking": -500, "Savings": 500, "Unclassified Expense": 0}


def test_retiring_a_transfer_rule_never_undoes_a_posted_move(session: Session, cash_rows, statement_row) -> None:
    _import_unruled(session, cash_rows, statement_row)
    _apply(session, _transfer_rule("Savings")).unwrap()
    _classify(session)
    entries = session.query(JournalEntry).count()

    _apply(session, "").unwrap()

    assert PlanClassifyRules(session).execute().unwrap() == []
    assert session.query(JournalEntry).count() == entries
    assert _by_kind(session, ClassificationKind.transfer)[0].final_account.name == "Savings"
    assert len(_by_kind(session, ClassificationKind.mirror)) == 1


def test_a_fault_on_the_mirror_rolls_the_whole_run_back(
    session: Session, cash_rows, statement_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_unruled(session, cash_rows, statement_row)
    _apply(session, _transfer_rule("Savings")).unwrap()
    moves = PlanClassifyRules(session).execute().unwrap()
    entries, groups = session.query(JournalEntry).count(), session.query(OperationGroup).count()
    monkeypatch.setattr(transfers_module, "set_mirror_service", lambda *args, **kwargs: Result.err(RuntimeError("boom")))

    assert ApplyClassifyRules(session).execute(moves).is_err

    assert session.query(JournalEntry).count() == entries
    assert session.query(OperationGroup).count() == groups
    assert _by_kind(session, ClassificationKind.transfer) == []


def test_an_import_between_preview_and_apply_gives_classify_plan_changed(
    session: Session, cash_rows, statement_row
) -> None:
    _import_unruled(session, cash_rows, statement_row)
    _apply(session, _transfer_rule("Savings")).unwrap()
    moves = PlanClassifyRules(session).execute().unwrap()
    ImportStatement(session).execute(
        "Savings", cash_rows([_in(statement_row, day=date(2026, 4, 3), reference="late")])
    ).unwrap()
    entries = session.query(JournalEntry).count()

    result = ApplyClassifyRules(session).execute(moves)

    assert isinstance(result.unwrap_err(), ClassifyPlanChanged)
    assert session.query(JournalEntry).count() == entries
