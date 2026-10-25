"""Issues 057 and 058: `list-config`, `get-config`, and the settings commands."""

import os
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from kohle.app.cli.cli import cli

from .test_schema_check import BEHIND, _build, _set_revision


def _default_path(tmp_path: Path) -> Path:
    return tmp_path / "xdg-data" / "kohle" / "kohle.db"


def test_list_config_shows_value_and_source(write_config, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("KOHLE_DB")
    config = tmp_path / "xdg-config" / "kohle" / "config.toml"

    result = CliRunner().invoke(cli, ["list-config"])
    assert result.exit_code == 0, result.output
    assert result.output == (
        f"ledger.path = {_default_path(tmp_path)}  (default)\n\nfile: {config} (not found)\n"
    )

    write_config('ledger.path = "~/books/kohle.db"\n')
    result = CliRunner().invoke(cli, ["list-config"])
    assert result.output == (
        f"ledger.path = {tmp_path / 'home' / 'books' / 'kohle.db'}  (file)\n\nfile: {config}\n"
    )

    monkeypatch.setenv("KOHLE_DB", "/tmp/scratch.db")
    result = CliRunner().invoke(cli, ["list-config"])
    assert result.output == f"ledger.path = /tmp/scratch.db  (KOHLE_DB)\n\nfile: {config}\n"


def _forbid_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_, **__):
        raise AssertionError("the ledger was opened")

    monkeypatch.setattr("kohle.app.cli.cli.open_ledger", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)


@pytest.mark.parametrize("command", [["list-config"], ["get-config", "ledger.path"]])
def test_config_commands_work_without_a_reachable_ledger(
    command: list[str], write_config, tmp_path: Path, monkeypatch
) -> None:
    missing = tmp_path / "nowhere" / "kohle.db"
    write_config(f'ledger.path = "{missing}"\n')
    monkeypatch.delenv("KOHLE_DB")
    _forbid_ledger(monkeypatch)

    result = CliRunner().invoke(cli, command)

    assert result.exit_code == 0, result.output
    assert str(missing) in result.output
    assert not missing.parent.exists()


@pytest.mark.parametrize("state", ["behind", "ahead"])
def test_config_commands_work_with_a_ledger_behind_or_ahead(state: str) -> None:
    db = _build()
    _set_revision(db, BEHIND if state == "behind" else "ffffffffffff")

    for command in (["list-config"], ["get-config", "ledger.path"]):
        result = CliRunner().invoke(cli, command)
        assert result.exit_code == 0, result.output
        assert str(db) in result.output


def test_get_config_prints_only_the_value_and_rejects_unknown_keys() -> None:
    result = CliRunner().invoke(cli, ["get-config", "ledger.path"])
    assert result.exit_code == 0, result.output
    assert result.output == os.environ["KOHLE_DB"] + "\n"

    result = CliRunner().invoke(cli, ["get-config", "nope"])
    assert result.exit_code == 1
    assert "unknown device key 'nope'" in result.output
    assert "ledger.path" in result.output


@pytest.mark.parametrize("command", [["list-config"], ["get-config", "ledger.path"]])
def test_config_commands_fail_on_a_bad_config(command: list[str], write_config) -> None:
    config = write_config('ledgr.path = "/x"\n')

    result = CliRunner().invoke(cli, command)

    assert result.exit_code == 1
    assert str(config) in result.output
    assert "ledgr.path" in result.output


@pytest.mark.skip(reason="058: not implemented")
def test_list_settings_ledger_line_shows_its_source() -> None:
    # TODO(058): (KOHLE_DB) / (file) / (default); exactly `ledger:   (in memory)`
    # with an injected factory (design 15.5).
    ...


@pytest.mark.skip(reason="058: not implemented")
def test_set_setting_refuses_device_keys_and_writes_nothing() -> None:
    # TODO(058): exit 1, message names the config path, Setting / Operation /
    # OperationGroup counts unchanged.
    ...


@pytest.mark.skip(reason="058: not implemented")
def test_set_setting_for_ledger_keys_is_unchanged() -> None:
    # TODO(058): `set-setting foo x` lists state; `set-setting state HE` works.
    ...
