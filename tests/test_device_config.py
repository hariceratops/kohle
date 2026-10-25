"""Issues 055 and 056: the device config file and its `ledger.path` key."""

from pathlib import Path

import pytest
from alembic import command
from alembic.util import CommandError
from click.testing import CliRunner

from kohle.app.cli.cli import cli
from kohle.db.connection import ledger_path
from kohle.db.schema import alembic_config
from kohle.infrastructure.device_config import DEVICE_KEYS, load_device_config

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


def _init_at(runner: CliRunner, write_init_rc) -> None:
    write_init_rc('state = "BW"\n')
    result = runner.invoke(cli, ["init"])
    assert result.exit_code == 0, result.output


def test_ledger_resolution_order_end_to_end(write_config, write_init_rc, tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    from_file = tmp_path / "from-file" / "kohle.db"
    from_env = tmp_path / "from-env" / "kohle.db"
    default = tmp_path / "xdg-data" / "kohle" / "kohle.db"
    write_config(f'ledger.path = "{from_file}"\n')

    # ledger.path only
    monkeypatch.delenv("KOHLE_DB")
    assert _resolved() == from_file
    _init_at(runner, write_init_rc)
    assert from_file.exists()
    result = runner.invoke(cli, ["list-settings"])
    assert result.exit_code == 0, result.output
    assert str(from_file) in result.output

    # KOHLE_DB wins over the file
    monkeypatch.setenv("KOHLE_DB", str(from_env))
    assert _resolved() == from_env
    _init_at(runner, write_init_rc)
    assert from_env.exists()
    assert str(from_env) in runner.invoke(cli, ["list-settings"]).output

    # KOHLE_DB="" counts as unset
    monkeypatch.setenv("KOHLE_DB", "")
    assert _resolved() == from_file

    # neither
    write_config("")
    monkeypatch.delenv("KOHLE_DB")
    assert _resolved() == default
    _init_at(runner, write_init_rc)
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


@pytest.mark.skip(reason="056: not implemented")
def test_unknown_key_stops_commands_but_not_help() -> None:
    # TODO(056): ledgr.path -> list-accounts exits non-zero naming the file and
    # ledger.path; --help and `list-accounts --help` exit 0 (design 15.3).
    ...


@pytest.mark.skip(reason="056: not implemented")
def test_unreadable_or_malformed_file_gives_one_line_without_traceback() -> None:
    # TODO(056): invalid value, TOML syntax error, non-UTF-8, directory at path.
    ...


@pytest.mark.skip(reason="056: not implemented")
def test_key_flattening_edge_cases() -> None:
    # TODO(056): quoted "ledger.path" unknown; {} and [ledger.path] invalid;
    # empty [ledger] gives defaults.
    ...


@pytest.mark.skip(reason="056: not implemented")
def test_bad_config_stops_init_and_migrate_before_any_write() -> None:
    # TODO(056): no file or parent dir at KOHLE_DB after init; ledger bytes
    # unchanged after migrate; zero rows with an injected factory.
    ...


@pytest.mark.skip(reason="056: not implemented")
def test_every_cli_command_is_a_kohle_command() -> None:
    # TODO(056): structural, every value in cli.commands is a _KohleCommand.
    ...
