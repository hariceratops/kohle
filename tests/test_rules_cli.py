"""Layer 2/3 — add-rule, show-rules, apply-rules, edit-rules through the CLI (design §17.3, §17.4, §17.6)."""

import re
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy.orm import sessionmaker

from kohle.app.cli.cli import cli
from kohle.core.result import Result
from kohle.domain.domain_errors import RuleError, RulesChanged
from kohle.domain.models import Operation, OperationGroup, Rule
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
    assert predicate("Miete Mai", Counterparty("Herr Vermieter", "DE89 3704 0044 0532 0130 00"))
    assert not predicate("Miete Mai", Counterparty("Herr Vermieter", "DE00 0000"))


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
            '[[rule]]\naccount = "Rent"\n[rule.when]\ndescription = "x"\n'
            '[[rule]]\naccount = "Rent"\n[rule.when]\ndescription = "x"\n',
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


@pytest.mark.skip(reason="TODO: 085 500 and 2000 to one IBAN land in two accounts")
def test_placeholder_partner_scenario() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason="TODO: 084/087/088 apply-rules, edit-rules, classify-rules refused; show-rules allowed")
def test_placeholder_readers() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason="TODO: 087 editor lookup, error banner, retry, recovery file")
def test_placeholder_edit_rules() -> None:
    raise NotImplementedError
