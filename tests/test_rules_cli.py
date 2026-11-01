"""Layer 2/3 — add-rule, show-rules, apply-rules, edit-rules through the CLI (design §17.3, §17.4, §17.6)."""

import re
import tomllib

import pytest
from click.testing import CliRunner
from sqlalchemy.orm import sessionmaker

from kohle.app.cli.cli import cli


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


@pytest.mark.skip(reason="TODO: 084 add-rule refuses a duplicate of a live rule only")
def test_placeholder_add_rule_duplicate() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason="TODO: 084 show-rules piped to apply-rules --yes reports No changes")
def test_placeholder_show_then_apply() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason="TODO: 084 one OperationGroup, stale base, fault rolls back")
def test_placeholder_apply_atomic() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason="TODO: 084 decline exits 1, --yes writes, bad file exits 1")
def test_placeholder_apply_prompts() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason="TODO: 085 500 and 2000 to one IBAN land in two accounts")
def test_placeholder_partner_scenario() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason="TODO: 084/087/088 apply-rules, edit-rules, classify-rules refused; show-rules allowed")
def test_placeholder_readers() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason="TODO: 087 editor lookup, error banner, retry, recovery file")
def test_placeholder_edit_rules() -> None:
    raise NotImplementedError
