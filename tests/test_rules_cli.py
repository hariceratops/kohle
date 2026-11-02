"""Layer 2/3 — add-rule, show-rules, apply-rules, edit-rules through the CLI (design §17.3, §17.4, §17.6)."""

import re
import tomllib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy.orm import sessionmaker

from kohle.app.cli.cli import cli
from kohle.core.result import Result
from kohle.domain.domain_errors import RuleError, RulesChanged
from kohle.domain.models import (
    Classification,
    JournalEntry,
    Operation,
    OperationGroup,
    Rule,
)
from kohle.plugin.importer_plugin import CashRow, StatementImporterPlugin
from kohle.services.journal_services import Counterparty
from kohle.use_cases import rules
from kohle.use_cases.conditions import When, compile_when
from kohle.use_cases.rules import ApplyRuleFile, ListRules, PlanRuleFile


def test_add_rule_appends_to_the_end_of_the_order_and_has_no_priority_option(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Groceries", "--type", "expense"], obj=session_factory)
    for pattern in ("REWE", "ALDI", "LIDL"):
        assert runner.invoke(cli, ["add-rule", pattern, "Groceries"], obj=session_factory).exit_code == 0
    runner.invoke(cli, ["remove-rule", "2"], obj=session_factory)
    runner.invoke(cli, ["add-rule", "EDEKA", "Groceries"], obj=session_factory)

    listing = runner.invoke(cli, ["list-rules"], obj=session_factory).output.splitlines()[2:]

    assert [line.split()[0] for line in listing] == ["1", "3", "4"]
    assert runner.invoke(cli, ["add-rule", "X", "Groceries", "--priority", "1"], obj=session_factory).exit_code == 2


def _seed(runner: CliRunner, session_factory: sessionmaker) -> None:
    for name in ("Groceries", "Rent"):
        runner.invoke(cli, ["add-account", name, "--type", "expense"], obj=session_factory)
    runner.invoke(cli, ["add-rule", "REWE|ALDI", "Groceries"], obj=session_factory)
    runner.invoke(cli, ["add-rule", r"^DE89\d+$", "Rent"], obj=session_factory)


def test_show_rules_prints_the_set_as_toml_in_evaluation_order_without_ids(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)

    first = runner.invoke(cli, ["show-rules"], obj=session_factory)
    second = runner.invoke(cli, ["show-rules"], obj=session_factory)

    assert first.exit_code == 0
    assert first.output == second.output
    data = tomllib.loads(first.output)
    assert data["rule"] == [
        {"account": "Groceries", "when": {"any_field": "REWE|ALDI"}},
        {"account": "Rent", "when": {"any_field": r"^DE89\d+$"}},
    ]
    assert re.fullmatch(r"[0-9a-f]{16}", data["base"])


def test_show_rules_base_depends_on_content_only(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    before = tomllib.loads(runner.invoke(cli, ["show-rules"], obj=session_factory).output)["base"]

    runner.invoke(cli, ["add-rule", "LIDL", "Groceries"], obj=session_factory)
    changed = tomllib.loads(runner.invoke(cli, ["show-rules"], obj=session_factory).output)["base"]
    runner.invoke(cli, ["remove-rule", "3"], obj=session_factory)
    runner.invoke(cli, ["add-rule", "LIDL", "Groceries"], obj=session_factory)
    runner.invoke(cli, ["remove-rule", "4"], obj=session_factory)
    restored = tomllib.loads(runner.invoke(cli, ["show-rules"], obj=session_factory).output)["base"]

    assert changed != before
    assert restored == before


def test_show_rules_on_an_empty_set_is_a_header_and_a_base(session_factory: sessionmaker) -> None:
    result = CliRunner().invoke(cli, ["show-rules"], obj=session_factory)

    assert result.exit_code == 0
    data = tomllib.loads(result.output)
    assert list(data) == ["base"]
    assert result.output.endswith("\n")


def _count(session_factory: sessionmaker, entity) -> int:
    with session_factory() as session:
        return session.query(entity).count()


def _live(session_factory: sessionmaker) -> list[tuple[int, str, int, str | None]]:
    """(id, condition, priority, note) of live rules in evaluation order."""
    with session_factory() as session:
        rules = session.query(Rule).filter(Rule.deleted_at.is_(None)).order_by(Rule.priority, Rule.id).all()
        return [(r.id, r.condition, r.priority, r.note) for r in rules]


def _write(tmp_path: Path, text: str) -> str:
    path = tmp_path / "rules.toml"
    path.write_text(text)
    return str(path)


def _apply(runner: CliRunner, session_factory: sessionmaker, tmp_path: Path, text: str, *args: str, **kwargs):
    return runner.invoke(cli, ["apply-rules", _write(tmp_path, text), *args], obj=session_factory, **kwargs)


def test_add_rule_refuses_a_duplicate_of_a_live_rule_only(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)

    duplicate = runner.invoke(cli, ["add-rule", "REWE|ALDI", "Groceries"], obj=session_factory)
    other_account = runner.invoke(cli, ["add-rule", "REWE|ALDI", "Rent"], obj=session_factory)
    runner.invoke(cli, ["remove-rule", "1"], obj=session_factory)
    after_retiring = runner.invoke(cli, ["add-rule", "REWE|ALDI", "Groceries"], obj=session_factory)

    assert duplicate.exit_code == 1
    assert "rule 1 already sends these lines to that account" in duplicate.output
    assert other_account.exit_code == 0
    assert after_retiring.exit_code == 0


def test_show_rules_piped_to_apply_rules_reports_no_changes_and_writes_nothing(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    runner.invoke(cli, ["add-rule", "LIDL", "Groceries"], obj=session_factory)
    shown = runner.invoke(cli, ["show-rules"], obj=session_factory).output
    groups = _count(session_factory, OperationGroup)
    operations = _count(session_factory, Operation)
    before = _live(session_factory)

    result = _apply(runner, session_factory, tmp_path, shown, "--yes")

    assert result.exit_code == 0, result.output
    assert result.output == "No changes\n"
    assert _count(session_factory, OperationGroup) == groups
    assert _count(session_factory, Operation) == operations
    assert _live(session_factory) == before


def test_apply_rules_accepts_the_new_conditions_and_matches_them_case_insensitively(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    text = (
        '[[rule]]\naccount = "Rent"\n[rule.when]\n'
        'description = "miete"\ncounterparty = "VERMIETER"\niban = "de89 3704 0044 0532 0130 00"\n'
    )

    result = _apply(runner, session_factory, tmp_path, text, "--yes")

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-1] == "Applied: 1 added, 2 retired, 0 reordered, 0 note changed, 0 unchanged"
    shown = tomllib.loads(runner.invoke(cli, ["show-rules"], obj=session_factory).output)
    assert shown["rule"] == [
        {
            "account": "Rent",
            "when": {"description": "miete", "counterparty": "VERMIETER", "iban": "DE89370400440532013000"},
        }
    ]
    predicate = compile_when(When(**shown["rule"][0]["when"]))
    assert predicate("Miete Mai", Counterparty("Herr Vermieter", "DE89 3704 0044 0532 0130 00"), Decimal(-1))
    assert not predicate("Miete Mai", Counterparty("Herr Vermieter", "DE00 0000"), Decimal(-1))


def test_apply_keeps_ids_on_a_move_and_a_note_edit_and_retires_a_changed_rule(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    runner.invoke(cli, ["add-rule", "LIDL", "Groceries"], obj=session_factory)
    text = (
        '[[rule]]\naccount = "Groceries"\n[rule.when]\nany_field = "LIDL"\n'
        '[[rule]]\naccount = "Groceries"\nnote = "weekly"\n[rule.when]\nany_field = "REWE|ALDI"\n'
        '[[rule]]\naccount = "Groceries"\n[rule.when]\nany_field = \'^DE89\\d+$\'\n'
    )

    result = _apply(runner, session_factory, tmp_path, text, "--yes")

    assert result.exit_code == 0, result.output
    live = _live(session_factory)
    assert [(rule_id, note) for rule_id, _, _, note in live] == [(3, None), (1, "weekly"), (4, None)]
    assert live[0][1] == '{ any_field = "LIDL" }'
    assert [priority for _, _, priority, _ in live] == sorted(priority for _, _, priority, _ in live)


def test_apply_rules_one_audit_group_holds_every_write(session_factory: sessionmaker, tmp_path: Path) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    groups = _count(session_factory, OperationGroup)
    text = (
        '[[rule]]\naccount = "Rent"\n[rule.when]\nany_field = "NEW"\n'
        '[[rule]]\naccount = "Groceries"\nnote = "n"\n[rule.when]\nany_field = "REWE|ALDI"\n'
    )

    assert _apply(runner, session_factory, tmp_path, text, "--yes").exit_code == 0

    with session_factory() as session:
        new_ops = session.query(Operation).filter(Operation.group_id > groups).all()
    assert _count(session_factory, OperationGroup) == groups + 1
    assert sorted((op.entity_type, op.action) for op in new_ops) == [
        ("rules", "create"),
        ("rules", "delete"),
        ("rules", "update"),
    ]


def test_apply_rules_refuses_when_the_stored_rules_changed_after_the_file_was_rendered(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    rendered = runner.invoke(cli, ["show-rules"], obj=session_factory).output
    runner.invoke(cli, ["add-rule", "LIDL", "Groceries"], obj=session_factory)
    before = _live(session_factory)
    groups = _count(session_factory, OperationGroup)

    result = _apply(runner, session_factory, tmp_path, "base = " + rendered.split("base = ")[1].split("\n")[0] + "\n", "--yes")

    assert result.exit_code == 1
    assert "the rules changed after this file was rendered" in result.output
    assert _live(session_factory) == before
    assert _count(session_factory, OperationGroup) == groups


def test_a_change_between_plan_and_apply_is_refused_with_nothing_written(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    text = '[[rule]]\naccount = "Rent"\n[rule.when]\nany_field = "NEW"\n'
    plan = PlanRuleFile(session_factory()).execute(text).unwrap()
    runner.invoke(cli, ["add-rule", "LIDL", "Groceries"], obj=session_factory)
    before = _live(session_factory)

    result = ApplyRuleFile(session_factory()).execute(text, plan.base)

    assert isinstance(result.unwrap_err(), RulesChanged)
    assert _live(session_factory) == before


def test_an_account_that_gains_a_child_between_plan_and_apply_fails_with_nothing_written(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    text = '[[rule]]\naccount = "Rent"\n[rule.when]\nany_field = "NEW"\n'
    plan = PlanRuleFile(session_factory()).execute(text).unwrap()
    runner.invoke(cli, ["add-account", "Flat", "--type", "expense", "--parent", "Rent"], obj=session_factory)
    before = _live(session_factory)

    result = ApplyRuleFile(session_factory()).execute(text, plan.base)

    assert "has sub-accounts" in str(result.unwrap_err())
    assert _live(session_factory) == before


def test_a_fault_on_the_second_add_rolls_everything_back(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    text = (
        '[[rule]]\naccount = "Rent"\n[rule.when]\nany_field = "ONE"\n'
        '[[rule]]\naccount = "Rent"\n[rule.when]\nany_field = "TWO"\n'
    )
    real = rules.add_rule_service
    calls = []

    def flaky(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            return Result.err(RuleError("disk on fire"))
        return real(*args, **kwargs)

    monkeypatch.setattr(rules, "add_rule_service", flaky)
    before = _live(session_factory)
    groups = _count(session_factory, OperationGroup)
    operations = _count(session_factory, Operation)

    result = ApplyRuleFile(session_factory()).execute(text, rules.rule_set_base(_stored(session_factory)))

    assert str(result.unwrap_err()) == "disk on fire"
    assert len(calls) == 2
    assert _live(session_factory) == before
    assert _count(session_factory, OperationGroup) == groups
    assert _count(session_factory, Operation) == operations


def _stored(session_factory: sessionmaker):
    session = session_factory()
    try:
        return ListRules(session).execute().unwrap()
    finally:
        session.close()


def test_declining_the_prompt_exits_1_and_writes_nothing(session_factory: sessionmaker, tmp_path: Path) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    before = _live(session_factory)
    groups = _count(session_factory, OperationGroup)
    text = '[[rule]]\naccount = "Rent"\n[rule.when]\nany_field = "NEW"\n'

    result = _apply(runner, session_factory, tmp_path, text, input="n\n")

    assert result.exit_code == 1
    assert "1 added, 2 retired, 0 reordered, 0 note changed, 0 unchanged" in result.output
    assert "Apply these changes?" in result.output
    assert "Applied" not in result.output
    assert _live(session_factory) == before
    assert _count(session_factory, OperationGroup) == groups


def test_confirming_the_prompt_applies(session_factory: sessionmaker, tmp_path: Path) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    text = '[[rule]]\naccount = "Rent"\n[rule.when]\nany_field = "NEW"\n'

    result = _apply(runner, session_factory, tmp_path, text, input="y\n")

    assert result.exit_code == 0, result.output
    assert [condition for _, condition, _, _ in _live(session_factory)] == ['{ any_field = "NEW" }']


def test_an_empty_file_shows_the_retired_count_before_anything_is_applied(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)

    declined = _apply(runner, session_factory, tmp_path, "", input="n\n")
    applied = _apply(runner, session_factory, tmp_path, "", "--yes")

    assert declined.exit_code == 1
    assert declined.output.startswith("0 added, 2 retired, 0 reordered, 0 note changed, 0 unchanged")
    assert applied.exit_code == 0
    assert _live(session_factory) == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[[rule]]\naccount = "Rent"\n[rule.when]\ndescription = "("\n', "rule 1, when.description: is not a valid pattern"),
        ('[[rule]]\naccount = "Rent"\n[rule.when]\nshoe = "x"\n', "rule 1, when.shoe: is not a known condition"),
        ('[[rule]]\naccount = "Nowhere"\n[rule.when]\ndescription = "x"\n', "rule 1, account: no account named 'Nowhere'"),
        ('[[rule]]\naccount = "Rent"\nwhen = {}\n', "rule 1, when: must be a table with at least one condition"),
        (
            ('[[rule]]\naccount = "Rent"\n[rule.when]\ndescription = "x"\n'
             '[[rule]]\naccount = "Rent"\n[rule.when]\ndescription = "x"\n'),
            "rule 2: has the same account and conditions as rule 1",
        ),
        ('[[rule]]\naccount = \n', "not valid TOML"),
    ],
)
def test_a_bad_file_exits_1_with_the_positioned_message_and_writes_nothing(
    session_factory: sessionmaker, tmp_path: Path, text: str, message: str
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    before = _live(session_factory)

    result = _apply(runner, session_factory, tmp_path, text, "--yes")

    assert result.exit_code == 1
    assert message in result.output
    assert _live(session_factory) == before


def test_a_rule_aimed_at_a_parent_account_is_rejected_with_its_position(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    runner.invoke(cli, ["add-account", "Flat", "--type", "expense", "--parent", "Rent"], obj=session_factory)

    result = _apply(runner, session_factory, tmp_path, '[[rule]]\naccount = "Rent"\n[rule.when]\ndescription = "x"\n', "--yes")

    assert result.exit_code == 1
    assert "rule 1, account: 'Rent' has sub-accounts" in result.output


def test_one_iban_splits_by_amount_between_two_accounts(
    session_factory: sessionmaker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    iban = "DE89370400440532013000"
    runner = CliRunner()
    for name, kind in (("Cash", "asset"), ("Household", "expense"), ("Savings", "expense")):
        runner.invoke(cli, ["add-account", name, "--type", kind], obj=session_factory)
    runner.invoke(cli, ["add-unit", "EUR", "Euro", "--kind", "currency"], obj=session_factory)
    text = (
        f'[[rule]]\naccount = "Household"\n[rule.when]\niban = "{iban}"\n'
        'amount = { min = 400, max = 600 }\ndirection = "out"\n\n'
        f'[[rule]]\naccount = "Savings"\n[rule.when]\niban = "{iban}"\n'
        "amount = { min = 1500 }\ndirection = \"out\"\n"
    )
    assert _apply(runner, session_factory, tmp_path, text, "--yes").exit_code == 0
    rows = [
        CashRow(
            entry_date=date(2026, 3, 1),
            reference="p-1",
            description="Transfer",
            amount=Decimal(-500),
            counterparty_name="Partner",
            counterparty_iban=iban,
        ),
        CashRow(
            entry_date=date(2026, 3, 2),
            reference="p-2",
            description="Transfer",
            amount=Decimal(-2000),
            counterparty_name="Partner",
            counterparty_iban=iban,
        ),
    ]

    class _Plugin(StatementImporterPlugin):
        name = "fake"

        def import_statement(self, statement_path: str):
            return Result.ok(rows)

    monkeypatch.setattr("kohle.app.cli.cli.load_plugins", lambda: {"fake": _Plugin()})
    statement = tmp_path / "statement.csv"
    statement.write_text("")

    result = runner.invoke(cli, ["import-statement", "fake", "Cash", str(statement)], obj=session_factory)

    assert result.exit_code == 0, result.output
    with session_factory() as session:
        landed = {
            entry.reference.split(":")[-1]: classification.final_account.name
            for classification, entry in session.query(Classification, JournalEntry)
            .join(JournalEntry, Classification.journal_entry_id == JournalEntry.id)
            .all()
        }
    assert landed == {"p-1": "Household", "p-2": "Savings"}
    shown = runner.invoke(cli, ["show-rules"], obj=session_factory).output
    assert "amount = { min = 400, max = 600 }" in shown
    assert 'direction = "out"' in shown
    again = _apply(runner, session_factory, tmp_path, shown, "--yes")
    assert again.exit_code == 0 and "No changes" in again.output


def test_nested_any_and_not_rules_round_trip_through_show_rules_and_classify_lines(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    text = (
        '[[rule]]\naccount = "Groceries"\n[rule.when]\nany = [\n  { description = "rewe" },\n'
        '  { counterparty = "edeka", not = { description = "pfand" } },\n]\n'
    )
    assert _apply(runner, session_factory, tmp_path, text, "--yes").exit_code == 0

    shown = runner.invoke(cli, ["show-rules"], obj=session_factory).output
    again = _apply(runner, session_factory, tmp_path, shown, "--yes")

    assert 'any = [\n  { description = "rewe" },\n  { counterparty = "edeka", not = { description = "pfand" } },\n]\n' in shown
    assert again.exit_code == 0 and again.output == "No changes\n"


def test_an_empty_any_is_refused_naming_the_rule_and_key_and_nothing_is_written(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    before = _live(session_factory)
    operations = _count(session_factory, Operation)

    result = _apply(runner, session_factory, tmp_path, '[[rule]]\naccount = "Rent"\n[rule.when]\nany = []\n', "--yes")

    assert result.exit_code == 1
    assert "rule 1, when.any:" in result.output
    assert _live(session_factory) == before
    assert _count(session_factory, Operation) == operations


def test_rule_writing_commands_are_refused_on_a_reader_and_show_rules_runs(
    session_factory: sessionmaker, write_config, tmp_path: Path
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)
    config = write_config('ledger.mode = "reader"\n')
    groups = _count(session_factory, OperationGroup)
    refusal = f"Error: this device is configured as a reader; `ledger.mode` is set in {config}\n"

    for argv in (
        ["apply-rules", _write(tmp_path, ""), "--yes"],
        ["edit-rules"],
        ["classify-rules", "--yes"],
    ):
        result = runner.invoke(cli, argv, obj=session_factory)
        assert result.exit_code == 1
        assert result.output == refusal

    assert runner.invoke(cli, ["show-rules"], obj=session_factory).exit_code == 0
    assert _count(session_factory, OperationGroup) == groups


class _Editor:
    """Scripted stand-in for click.edit: each call returns the next reply, or
    calls it with the text it was given."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *replies) -> None:
        self.replies = list(replies)
        self.texts: list[str] = []
        self.editors: list[str | None] = []
        monkeypatch.setattr("click.edit", self)

    def __call__(self, text=None, editor=None, **kwargs):
        self.texts.append(text)
        self.editors.append(editor)
        reply = self.replies.pop(0)
        return reply(text) if callable(reply) else reply


def _edit(runner: CliRunner, session_factory: sessionmaker, **kwargs):
    return runner.invoke(cli, ["edit-rules"], obj=session_factory, **kwargs)


_NEW_RULE = '[[rule]]\naccount = "Rent"\n[rule.when]\nany_field = "NEW"\n'


@pytest.fixture
def editor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "ed")


def test_edit_rules_without_an_editor_fails_and_never_opens_one(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    editor = _Editor(monkeypatch)
    runner = CliRunner()
    _seed(runner, session_factory)
    before = _live(session_factory)

    result = _edit(runner, session_factory)

    assert result.exit_code == 1
    assert "no editor: set $VISUAL or $EDITOR" in result.output
    assert editor.texts == []
    assert _live(session_factory) == before


def test_visual_wins_over_editor_and_the_editor_gets_the_rendered_rules(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VISUAL", "visual-ed")
    monkeypatch.setenv("EDITOR", "plain-ed")
    editor = _Editor(monkeypatch, None)
    runner = CliRunner()
    _seed(runner, session_factory)

    _edit(runner, session_factory)

    assert editor.editors == ["visual-ed"]
    assert editor.texts == [runner.invoke(cli, ["show-rules"], obj=session_factory).output]


@pytest.mark.usefixtures("editor_env")
def test_quitting_the_editor_without_saving_changes_nothing(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    _Editor(monkeypatch, None)
    runner = CliRunner()
    _seed(runner, session_factory)
    before = _live(session_factory)
    groups = _count(session_factory, OperationGroup)

    result = _edit(runner, session_factory)

    assert result.exit_code == 0
    assert "No changes; nothing applied" in result.output
    assert _live(session_factory) == before
    assert _count(session_factory, OperationGroup) == groups


@pytest.mark.usefixtures("editor_env")
def test_a_bad_file_reopens_the_editor_with_a_banner_naming_the_error_and_writes_nothing(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = '[[rule]]\naccount = "Rent"\n[rule.when]\ndescription = "("\n'
    editor = _Editor(monkeypatch, bad, None)
    runner = CliRunner()
    _seed(runner, session_factory)
    before = _live(session_factory)

    result = _edit(runner, session_factory)

    assert result.exit_code == 0
    banner = editor.texts[1].splitlines()[:2]
    assert banner[0].startswith("# !! kohle: not applied.")
    assert banner[1].startswith("# !! rule 1, when.description: is not a valid pattern")
    assert editor.texts[1].endswith(bad)
    assert _live(session_factory) == before


@pytest.mark.usefixtures("editor_env")
def test_a_toml_syntax_error_line_number_matches_the_reopened_buffer(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = '[[rule]]\naccount = "Rent"\n[rule.when]\ndescription =\n'
    editor = _Editor(monkeypatch, bad, None)

    _edit(CliRunner(), session_factory)

    reopened = editor.texts[1]
    match = re.search(r"at line (\d+)", reopened.splitlines()[1])
    assert match
    assert reopened.splitlines()[int(match.group(1)) - 1] == "description ="


@pytest.mark.usefixtures("editor_env")
def test_a_fixed_file_after_a_bad_one_is_applied_with_the_banner_stripped(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = '[[rule]]\naccount = "Rent"\n[rule.when]\ndescription = "("\n'
    runner = CliRunner()
    _seed(runner, session_factory)
    editor = _Editor(monkeypatch, bad, lambda reopened: reopened.replace('description = "("', 'description = "x"'))

    result = _edit(runner, session_factory, input="y\n")

    assert result.exit_code == 0, result.output
    assert len(editor.texts) == 2
    assert "Applied: 1 added, 2 retired" in result.output
    assert [condition for _, condition, _, _ in _live(session_factory)] == ['{ description = "x" }']


@pytest.mark.usefixtures("editor_env")
def test_declining_the_confirmation_after_edit_writes_nothing(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    _Editor(monkeypatch, _NEW_RULE)
    runner = CliRunner()
    _seed(runner, session_factory)
    before = _live(session_factory)
    groups = _count(session_factory, OperationGroup)

    result = _edit(runner, session_factory, input="n\n")

    assert result.exit_code == 1
    assert "1 added, 2 retired, 0 reordered, 0 note changed, 0 unchanged" in result.output
    assert _live(session_factory) == before
    assert _count(session_factory, OperationGroup) == groups


@pytest.mark.usefixtures("editor_env")
def test_saving_the_rendered_text_unchanged_reports_no_changes(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    _Editor(monkeypatch, lambda text: text)
    runner = CliRunner()
    _seed(runner, session_factory)
    groups = _count(session_factory, OperationGroup)

    result = _edit(runner, session_factory)

    assert result.exit_code == 0
    assert result.output == "No changes\n"
    assert _count(session_factory, OperationGroup) == groups


@pytest.mark.usefixtures("editor_env")
def test_a_rule_added_while_editing_is_refused_and_the_users_text_is_saved(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    _seed(runner, session_factory)

    edited_text = {}

    def capture(text: str) -> str:
        assert CliRunner().invoke(cli, ["add-rule", "LIDL", "Groceries"], obj=session_factory).exit_code == 0
        edited_text["value"] = text + "\n" + _NEW_RULE
        return edited_text["value"]

    _Editor(monkeypatch, capture)

    result = _edit(runner, session_factory, input="y\n")

    assert result.exit_code == 1
    assert "the rules changed after this file was rendered" in result.output
    match = re.search(r"your edits are saved in (\S+)", result.output)
    assert match
    saved = Path(match.group(1))
    try:
        assert saved.read_text() == edited_text["value"]
    finally:
        saved.unlink()
    assert len(_live(session_factory)) == 3
