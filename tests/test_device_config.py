"""Issues 055 and 056: the device config file and its `ledger.path` key."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.util import CommandError
from click.testing import CliRunner
from sqlalchemy import select

from kohle.app.cli.cli import _KohleCommand, cli
from kohle.db.connection import ledger_path
from kohle.db.schema import alembic_config
from kohle.domain.models import Account, OperationGroup
from kohle.infrastructure.device_config import DEVICE_KEYS, load_device_config

BEHIND = "d4e7a8c15b92"
EXPECTED = "an absolute path, or one starting with ~"


def _resolved() -> Path:
    return ledger_path(load_device_config().unwrap())


def test_ledger_path_validator_accepts_expands_and_rejects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "h"))
    validate = DEVICE_KEYS["ledger.path"].validate

    assert validate("/abs/kohle.db").unwrap() == Path("/abs/kohle.db")
    assert validate("~/k.db").unwrap() == tmp_path / "h" / "k.db"
    for bad in ("kohle.db", "", 1, {}, "~nosuchuser/k.db"):
        err = validate(bad).unwrap_err()
        assert str(err) == f"invalid ledger.path {bad!r}; expected {EXPECTED}"


def test_table_form_and_dotted_form_load_equal(write_config) -> None:
    write_config('[ledger]\npath = "/x"\n')
    table_form = load_device_config().unwrap().values
    write_config('ledger.path = "/x"\n')
    dotted_form = load_device_config().unwrap().values

    assert table_form == dotted_form == {"ledger.path": Path("/x")}


def _init_at(runner: CliRunner, write_init_toml) -> None:
    write_init_toml('state = "BW"\n')
    result = runner.invoke(cli, ["init"])
    assert result.exit_code == 0, result.output


def test_ledger_resolution_order_end_to_end(write_config, write_init_toml, tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    from_file = tmp_path / "from-file" / "kohle.db"
    from_env = tmp_path / "from-env" / "kohle.db"
    default = tmp_path / "xdg-data" / "kohle" / "kohle.db"
    write_config(f'ledger.path = "{from_file}"\n')

    monkeypatch.delenv("KOHLE_DB")
    assert _resolved() == from_file
    _init_at(runner, write_init_toml)
    assert from_file.exists()
    result = runner.invoke(cli, ["list-settings"])
    assert result.exit_code == 0, result.output
    assert str(from_file) in result.output

    monkeypatch.setenv("KOHLE_DB", str(from_env))
    assert _resolved() == from_env
    _init_at(runner, write_init_toml)
    assert from_env.exists()
    assert str(from_env) in runner.invoke(cli, ["list-settings"]).output

    # KOHLE_DB="" counts as unset
    monkeypatch.setenv("KOHLE_DB", "")
    assert _resolved() == from_file

    write_config("")
    monkeypatch.delenv("KOHLE_DB")
    assert _resolved() == default
    _init_at(runner, write_init_toml)
    assert default.exists()
    assert str(default) in runner.invoke(cli, ["list-settings"]).output


def test_relative_ledger_path_is_refused_naming_the_file(write_config) -> None:
    config = write_config('ledger.path = "kohle.db"\n')

    result = CliRunner().invoke(cli, ["list-accounts"])

    assert result.exit_code == 1
    assert str(config) in result.output
    assert "ledger.path" in result.output
    assert "Traceback" not in result.output


def test_missing_config_file_runs_with_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KOHLE_DB")

    loaded = load_device_config().unwrap()
    assert loaded.values == {}
    assert loaded.path == tmp_path / "xdg-config" / "kohle" / "config.toml"
    assert not loaded.path.exists()
    assert _resolved() == tmp_path / "xdg-data" / "kohle" / "kohle.db"

    result = CliRunner().invoke(cli, ["list-accounts"])

    assert "no ledger at" in result.output
    assert "Traceback" not in result.output


def test_ledger_path_naming_a_missing_file_gives_the_no_ledger_error(write_config, tmp_path: Path, monkeypatch) -> None:
    missing = tmp_path / "nowhere" / "kohle.db"
    write_config(f'ledger.path = "{missing}"\n')
    monkeypatch.delenv("KOHLE_DB")

    result = CliRunner().invoke(cli, ["list-accounts"])

    assert result.exit_code == 1
    assert f"no ledger at {missing}; run `kohle-cli init`" in result.output


def test_alembic_env_uses_ledger_path_and_names_the_file_on_a_bad_value(
    write_config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KOHLE_DB")
    db = tmp_path / "alembic.db"
    db.touch()
    write_config(f'ledger.path = "{db}"\n')

    command.upgrade(alembic_config(), "head")

    assert db.stat().st_size > 0

    config = write_config('ledger.path = "kohle.db"\n')
    with pytest.raises(CommandError) as raised:
        command.upgrade(alembic_config(), "head")
    assert str(config) in str(raised.value)
    assert "ledger.path" in str(raised.value)


def test_unknown_key_stops_commands_but_not_help(write_config) -> None:
    config = write_config('ledgr.path = "/x"\n')
    runner = CliRunner()

    result = runner.invoke(cli, ["list-accounts"])

    assert result.exit_code == 1
    assert result.output == (
        f"Error: {config}: unknown device key 'ledgr.path'; known device keys: ledger.path, ledger.mode\n"
    )
    for args in (["--help"], ["list-accounts", "--help"]):
        assert runner.invoke(cli, args).exit_code == 0


def _one_line_error(result, config: Path, *fragments: str) -> None:
    assert result.exit_code == 1
    assert result.output.count("\n") == 1
    assert result.output.startswith(f"Error: {config}: ")
    assert "Traceback" not in result.output
    for fragment in fragments:
        assert fragment in result.output


def test_unreadable_or_malformed_file_gives_one_line_without_traceback(write_config) -> None:
    runner = CliRunner()

    config = write_config('ledger.path = "kohle.db"\n')
    _one_line_error(runner.invoke(cli, ["list-accounts"]), config, "ledger.path", EXPECTED)

    config = write_config("ledger.path =\n")
    _one_line_error(runner.invoke(cli, ["list-accounts"]), config, "line 1")

    config.write_bytes(b'ledger.path = "\xe9"\n')
    _one_line_error(runner.invoke(cli, ["list-accounts"]), config)

    config.unlink()
    config.mkdir()
    _one_line_error(runner.invoke(cli, ["list-accounts"]), config, "directory")


def test_key_flattening_edge_cases(write_config) -> None:
    runner = CliRunner()

    config = write_config('"ledger.path" = "/x"\n')
    result = runner.invoke(cli, ["list-accounts"])
    _one_line_error(result, config, "unknown device key '\"ledger.path\"'")

    for content, bad in (("ledger.path = {}\n", "{}"), ("[ledger.path]\n", "{}")):
        config = write_config(content)
        _one_line_error(runner.invoke(cli, ["list-accounts"]), config, f"invalid ledger.path {bad}", EXPECTED)

    write_config("[ledger]\n")
    assert load_device_config().unwrap().values == {}
    result = runner.invoke(cli, ["list-accounts"])
    assert "no ledger at" in result.output


def test_bad_config_stops_init_and_migrate_before_any_write(
    write_config, write_init_toml, session_factory
) -> None:
    runner = CliRunner()
    db = Path(os.environ["KOHLE_DB"])
    write_init_toml('state = "BW"\n')
    write_config('ledgr.path = "/x"\n')

    result = runner.invoke(cli, ["init"])

    assert result.exit_code == 1
    assert "unknown device key" in result.output
    assert not db.exists()
    assert not db.parent.exists()

    write_config("")
    db.parent.mkdir(parents=True)
    db.touch()
    command.upgrade(alembic_config(), BEHIND)
    before = db.read_bytes()
    write_config('ledgr.path = "/x"\n')

    result = runner.invoke(cli, ["migrate"])

    assert result.exit_code == 1
    assert "unknown device key" in result.output
    assert db.read_bytes() == before

    result = runner.invoke(cli, ["add-account", "Cash", "--type", "asset"], obj=session_factory)

    assert result.exit_code == 1
    with session_factory() as session:
        assert session.scalars(select(Account)).all() == []
        assert session.scalars(select(OperationGroup)).all() == []


def test_every_cli_command_is_a_kohle_command() -> None:
    assert all(isinstance(c, _KohleCommand) for c in cli.commands.values())
