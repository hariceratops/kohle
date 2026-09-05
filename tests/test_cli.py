"""Layer 4 — CLI tests through Click's CliRunner.

Issue 009 wires the session factory onto Click's context object, so a
`CliRunner` invocation can be pointed at the `session_factory` fixture
instead of the real `kohle.db`. This layer covers what the layers below
cannot: that a domain error reaches the user as a message rather than a
traceback, and that output renders the way the acceptance criteria describe.
"""

from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from sqlalchemy.orm import sessionmaker

from kohle.app.cli.cli import cli
from kohle.domain.models import Account


def test_injected_factory_is_used_and_real_db_is_untouched(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_session_local():
        raise AssertionError("session_local must not be called when a factory is injected via obj")

    monkeypatch.setattr("kohle.app.cli.cli.session_local", forbidden_session_local)

    runner = CliRunner()
    result = runner.invoke(cli, ["add-account", "Alice", "--type", "asset"], obj=session_factory)

    assert result.exit_code == 0
    assert "Added account Alice" in result.output

    session = session_factory()
    try:
        accounts = session.query(Account).all()
        assert [a.name for a in accounts] == ["Alice"]
    finally:
        session.close()


def test_default_obj_falls_back_to_session_local(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel_factory = Mock(side_effect=lambda: Mock())
    monkeypatch.setattr("kohle.app.cli.cli.session_local", sentinel_factory)

    runner = CliRunner()
    runner.invoke(cli, ["list-accounts"])

    assert sentinel_factory.called


def test_record_posts_an_entry_and_reports_success(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Unallocated", "--type", "asset"], obj=session_factory)

    result = runner.invoke(
        cli,
        ["record", "2026-03-01", "Withdraw cash", "200", "--from", "Checking", "--to", "Unallocated"],
        obj=session_factory,
    )

    assert result.exit_code == 0
    assert "200" in result.output
    assert "EUR" in result.output
    assert "credited Checking" in result.output
    assert "debited Unallocated" in result.output


def test_record_unknown_account_prints_readable_message(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)

    result = runner.invoke(
        cli,
        ["record", "2026-03-01", "Withdraw cash", "200", "--from", "Checking", "--to", "Nope"],
        obj=session_factory,
    )

    assert result.exception is None
    assert "Failed: Account Nope not found" in result.output


def test_placeholder(session_factory: sessionmaker) -> None:
    # TODO: a non-zero exit code accompanies a failed command
    # TODO: record-split with a malformed --line names the offending value
    # TODO: balance renders one row per unit through tabulate
    # TODO: list-accounts renders nesting with |- connectors, since tabulate
    #       strips leading whitespace (issue 007)
    # TODO: the operations command lists the audit trail (issue 008)
    assert True
