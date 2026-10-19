"""Issue 047: one per-user ledger location, migrations packaged with kohle."""

import configparser
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from click.testing import CliRunner

from alembic import command
from kohle.app.cli.cli import cli
from kohle.db.connection import ledger_path
from kohle.db.schema import SCRIPT_LOCATION, alembic_config

ROOT = Path(__file__).resolve().parents[1]


def test_kohle_db_wins_over_xdg_data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOHLE_DB", str(tmp_path / "chosen.db"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    assert ledger_path() == tmp_path / "chosen.db"


@pytest.mark.parametrize("kohle_db", [None, ""])
def test_xdg_data_home_is_used_when_kohle_db_is_unset_or_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kohle_db: str | None
) -> None:
    if kohle_db is None:
        monkeypatch.delenv("KOHLE_DB")
    else:
        monkeypatch.setenv("KOHLE_DB", kohle_db)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    assert ledger_path() == tmp_path / "xdg" / "kohle" / "kohle.db"


@pytest.mark.parametrize("xdg", [None, ""])
def test_home_local_share_is_the_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, xdg: str | None
) -> None:
    monkeypatch.delenv("KOHLE_DB")
    if xdg is None:
        monkeypatch.delenv("XDG_DATA_HOME")
    else:
        monkeypatch.setenv("XDG_DATA_HOME", xdg)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert ledger_path() == tmp_path / ".local" / "share" / "kohle" / "kohle.db"


def test_two_working_directories_read_the_same_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KOHLE_DB")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    db = ledger_path()
    db.parent.mkdir(parents=True)
    db.touch()
    command.upgrade(alembic_config(), "head")

    runner = CliRunner()
    seen = []
    for name in ("one", "two"):
        cwd = tmp_path / name
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        result = runner.invoke(cli, ["list-accounts"])
        assert result.exit_code == 0, result.output
        seen.append(result.output)

    assert "People" in seen[0]
    assert seen[0] == seen[1]
    assert not (tmp_path / "one" / "kohle.db").exists()
    assert not (tmp_path / "two" / "kohle.db").exists()


def test_migrations_are_found_from_the_package_outside_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    script = ScriptDirectory.from_config(alembic_config())

    assert script.get_current_head() is not None


def test_alembic_ini_names_the_same_script_location_as_the_code() -> None:
    ini = configparser.ConfigParser()
    ini.read(ROOT / "alembic.ini")

    assert ini["alembic"]["script_location"] == SCRIPT_LOCATION
    assert not ini.has_option("alembic", "sqlalchemy.url")


def test_the_repo_alembic_command_finds_the_ledger_the_way_kohle_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic.config import Config

    db = tmp_path / "dev.db"
    db.touch()
    monkeypatch.setenv("KOHLE_DB", str(db))
    config = Config(str(ROOT / "alembic.ini"))

    command.upgrade(config, "head")

    assert db.stat().st_size > 0
