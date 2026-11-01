"""Layer 2/3 — add-rule, show-rules, apply-rules, edit-rules through the CLI (design §17.3, §17.4, §17.6)."""

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
