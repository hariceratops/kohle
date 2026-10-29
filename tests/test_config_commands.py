"""Issues 057 and 058: `list-config`, `get-config`, and the settings commands."""

import os
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from kohle.app.cli.cli import cli
from kohle.domain.models import Operation, OperationGroup, Setting

from .test_schema_check import BEHIND, _build, _set_revision


def _default_path(tmp_path: Path) -> Path:
    return tmp_path / "xdg-data" / "kohle" / "kohle.db"


def test_list_config_shows_value_and_source(write_config, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("KOHLE_DB")
    config = tmp_path / "xdg-config" / "kohle" / "config.toml"

    result = CliRunner().invoke(cli, ["list-config"])
    assert result.exit_code == 0, result.output
    assert result.output == (
        f"ledger.path = {_default_path(tmp_path)}  (default)\n"
        f"ledger.mode = writer  (default)\n\nfile: {config} (not found)\n"
    )

    write_config('ledger.path = "~/books/kohle.db"\n')
    result = CliRunner().invoke(cli, ["list-config"])
    assert result.output == (
        f"ledger.path = {tmp_path / 'home' / 'books' / 'kohle.db'}  (file)\n"
        f"ledger.mode = writer  (default)\n\nfile: {config}\n"
    )

    monkeypatch.setenv("KOHLE_DB", "/tmp/scratch.db")
    result = CliRunner().invoke(cli, ["list-config"])
    assert result.output == (
        f"ledger.path = /tmp/scratch.db  (KOHLE_DB)\nledger.mode = writer  (default)\n\nfile: {config}\n"
    )


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


def test_list_settings_ledger_line_shows_its_source(
    write_config, run_init, write_init_toml, tmp_path: Path, monkeypatch
) -> None:
    write_init_toml('state = "BW"\n')
    db = tmp_path / "books" / "kohle.db"
    monkeypatch.setenv("KOHLE_DB", str(db))
    assert run_init().exit_code == 0

    result = CliRunner().invoke(cli, ["list-settings"])
    assert f"ledger:   {db.resolve()}  (KOHLE_DB)\n" in result.output

    monkeypatch.delenv("KOHLE_DB")
    write_config(f'ledger.path = "{db}"\n')
    result = CliRunner().invoke(cli, ["list-settings"])
    assert f"ledger:   {db.resolve()}  (file)\n" in result.output

    default = _default_path(tmp_path)
    default.parent.mkdir(parents=True)
    db.rename(default)
    write_config("")
    result = CliRunner().invoke(cli, ["list-settings"])
    assert f"ledger:   {default.resolve()}  (default)\n" in result.output


def test_list_settings_in_memory_has_no_source(session_factory) -> None:
    result = CliRunner().invoke(cli, ["list-settings"], obj=session_factory)

    assert result.exit_code == 0, result.output
    assert "ledger:   (in memory)\n" in result.output


def _counts(session_factory) -> tuple[int, int, int]:
    with session_factory() as s:
        return tuple(
            s.query(model).count() for model in (Setting, Operation, OperationGroup)
        )  # type: ignore[return-value]


def test_set_setting_refuses_device_keys_and_writes_nothing(
    session_factory, write_config
) -> None:
    config = write_config("")
    before = _counts(session_factory)

    args = ["set-setting", "ledger.path", "/x"]
    result = CliRunner().invoke(cli, args, obj=session_factory)

    assert result.exit_code == 1
    assert f"`ledger.path` is a device key; edit {config}" in result.output
    assert _counts(session_factory) == before


def test_set_setting_for_ledger_keys_refuses_unknown_and_state(session_factory) -> None:
    result = CliRunner().invoke(cli, ["set-setting", "foo", "x"], obj=session_factory)
    assert result.exit_code == 1
    assert "unknown setting 'foo'; there are no ledger settings" in result.output

    result = CliRunner().invoke(cli, ["set-setting", "state", "HE"], obj=session_factory)
    assert result.exit_code == 1
    assert "move-state --from" in result.output
