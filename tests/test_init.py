import os
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from click.testing import CliRunner
from sqlalchemy import create_engine, text

from kohle.app.cli.cli import cli
from kohle.core.result import Result
from kohle.db import schema
from kohle.db.schema import alembic_config
from kohle.domain.domain_errors import SettingError
from kohle.use_cases.settings import SetSettings


def _head() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def test_init_then_list_accounts_and_list_settings(write_init_rc, run_init, tmp_path: Path) -> None:
    write_init_rc('state = "BW"\n')
    db = Path(os.environ["KOHLE_DB"])

    result = run_init()

    assert result.exit_code == 0, result.output
    assert db.is_file()
    accounts = CliRunner().invoke(cli, ["list-accounts"])
    assert accounts.exit_code == 0, accounts.output
    assert "People" in accounts.output
    settings = CliRunner().invoke(cli, ["list-settings"])
    assert settings.exit_code == 0, settings.output
    assert "state = BW" in settings.output
    assert f"ledger:   {db.resolve()}" in settings.output
    assert f"revision: {_head()}" in settings.output


def test_init_works_from_outside_the_checkout(write_init_rc, run_init, tmp_path: Path, monkeypatch) -> None:
    write_init_rc('state = "HE"\n')
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = run_init()

    assert result.exit_code == 0, result.output
    assert Path(os.environ["KOHLE_DB"]).is_file()


def test_init_creates_the_parent_directory(write_init_rc, run_init) -> None:
    write_init_rc('state = "BW"\n')
    db = Path(os.environ["KOHLE_DB"])
    assert not db.parent.exists()

    assert run_init().exit_code == 0
    assert db.parent.is_dir()


def test_init_leaves_no_staged_file_behind(write_init_rc, run_init) -> None:
    write_init_rc('state = "BW"\n')
    db = Path(os.environ["KOHLE_DB"])

    run_init()

    assert [p.name for p in db.parent.iterdir()] == [db.name]


def test_missing_init_file_names_the_path(run_init, tmp_path: Path) -> None:
    result = run_init()

    assert result.exit_code == 1
    assert str(tmp_path / "xdg-config" / "kohle" / "init.rc") in result.output
    assert not Path(os.environ["KOHLE_DB"]).parent.exists()


def test_init_file_falls_back_to_home_config(run_init, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    rc = tmp_path / "home" / ".config" / "kohle" / "init.rc"
    rc.parent.mkdir(parents=True)
    rc.write_text('state = "NW"\n')

    assert run_init().exit_code == 0
    assert "state = NW" in CliRunner().invoke(cli, ["list-settings"]).output


def _assert_rejected(result, db: Path, *fragments: str) -> None:
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    for fragment in fragments:
        assert fragment in result.output
    assert not db.exists()
    assert not db.parent.exists()


def test_invalid_state_lists_the_valid_codes(write_init_rc, run_init) -> None:
    rc = write_init_rc('state = "XX"\n')

    result = run_init()

    _assert_rejected(result, Path(os.environ["KOHLE_DB"]), str(rc), "'XX'", "BB, BE, BW, BY")


def test_non_string_state_is_invalid(write_init_rc, run_init) -> None:
    write_init_rc("state = 1\n")

    _assert_rejected(run_init(), Path(os.environ["KOHLE_DB"]), "invalid state 1", "BB, BE, BW, BY")


def test_unknown_key_lists_the_known_keys(write_init_rc, run_init) -> None:
    write_init_rc('state = "BW"\nfoo = 1\n')

    _assert_rejected(run_init(), Path(os.environ["KOHLE_DB"]), "unknown setting 'foo'", "known settings: state")


def test_a_typo_reports_unknown_not_missing(write_init_rc, run_init) -> None:
    write_init_rc('stat = "BW"\n')

    result = run_init()

    _assert_rejected(result, Path(os.environ["KOHLE_DB"]), "unknown setting 'stat'")
    assert "missing" not in result.output


def test_file_without_state_is_refused(write_init_rc, run_init) -> None:
    rc = write_init_rc("# nothing here\n")

    _assert_rejected(run_init(), Path(os.environ["KOHLE_DB"]), str(rc), "missing state")


def test_invalid_toml_is_refused(write_init_rc, run_init) -> None:
    rc = write_init_rc("state = \n")

    _assert_rejected(run_init(), Path(os.environ["KOHLE_DB"]), str(rc))


def test_init_takes_no_flags(write_init_rc) -> None:
    write_init_rc('state = "BW"\n')

    result = CliRunner().invoke(cli, ["init", "--state", "BY"])

    assert result.exit_code == 2
    assert not Path(os.environ["KOHLE_DB"]).parent.exists()


def test_the_settings_write_is_audited(write_init_rc, run_init) -> None:
    write_init_rc('state = "BW"\n')
    run_init()

    ops = CliRunner().invoke(cli, ["list-operations"])

    rows = [line.split() for line in ops.output.splitlines()[2:]]
    assert rows == [["1", "settings", "1", "create"]]


def _snapshot(db: Path) -> tuple[bytes, int]:
    return db.read_bytes(), db.stat().st_mtime_ns


def _init_then(write_init_rc, run_init, state: str = "BW") -> Path:
    write_init_rc(f'state = "{state}"\n')
    assert run_init().exit_code == 0
    return Path(os.environ["KOHLE_DB"])


def test_rerun_at_head_with_the_same_state_is_already_initialized(write_init_rc, run_init) -> None:
    db = _init_then(write_init_rc, run_init)
    before = _snapshot(db)

    result = run_init()

    assert result.exit_code == 0, result.output
    assert f"already initialized at {db}, revision {_head()}" in result.output
    assert _snapshot(db) == before


def test_existing_ledger_behind_points_to_migrate(write_init_rc, run_init) -> None:
    write_init_rc('state = "BW"\n')
    db = Path(os.environ["KOHLE_DB"])
    db.parent.mkdir(parents=True)
    db.touch()
    engine = create_engine(f"sqlite:///{db}")
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "d4e7a8c15b92")
    engine.dispose()
    before = _snapshot(db)

    result = run_init()

    assert result.exit_code == 1
    assert "migrate" in result.output
    assert "Traceback" not in result.output
    assert _snapshot(db) == before


def test_existing_ledger_with_a_different_state_points_to_set_setting(write_init_rc, run_init) -> None:
    db = _init_then(write_init_rc, run_init, "BW")
    write_init_rc('state = "BY"\n')
    before = _snapshot(db)

    result = run_init()

    assert result.exit_code == 1
    assert "set-setting state BY" in result.output
    assert "state = BW" in result.output
    assert _snapshot(db) == before


def test_existing_ledger_with_state_unset_points_to_set_setting(write_init_rc, run_init) -> None:
    db = _init_then(write_init_rc, run_init)
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM settings"))
    engine.dispose()
    before = _snapshot(db)

    result = run_init()

    assert result.exit_code == 1
    assert "set-setting state BW" in result.output
    assert _snapshot(db) == before


def test_file_errors_read_the_same_with_or_without_a_database(write_init_rc, run_init) -> None:
    rc = write_init_rc('state = "XX"\n')
    without = run_init()
    db = Path(os.environ["KOHLE_DB"])
    write_init_rc('state = "BW"\n')
    assert run_init().exit_code == 0
    write_init_rc('state = "XX"\n')
    before = _snapshot(db)

    with_db = run_init()

    assert with_db.exit_code == without.exit_code == 1
    assert with_db.output == without.output
    assert str(rc) in with_db.output
    assert _snapshot(db) == before


def _assert_nothing_left(db: Path) -> None:
    assert not db.exists()
    assert not list(db.parent.glob(f".{db.name}.*"))


def test_failed_populate_leaves_nothing(write_init_rc, run_init, monkeypatch: pytest.MonkeyPatch) -> None:
    write_init_rc('state = "BW"\n')
    db = Path(os.environ["KOHLE_DB"])
    with monkeypatch.context() as patched:
        patched.setattr(SetSettings, "execute", lambda self, values: Result.err(SettingError("nope")))
        result = run_init()

    assert result.exit_code == 1
    assert "nope" in result.output
    _assert_nothing_left(db)
    assert run_init().exit_code == 0


def test_interrupted_populate_leaves_nothing(write_init_rc, run_init, monkeypatch: pytest.MonkeyPatch) -> None:
    write_init_rc('state = "BW"\n')
    db = Path(os.environ["KOHLE_DB"])

    def interrupt(self, values):
        raise KeyboardInterrupt

    with monkeypatch.context() as patched:
        patched.setattr(SetSettings, "execute", interrupt)
        result = run_init()

    assert isinstance(result.exception, KeyboardInterrupt) or result.exit_code != 0
    _assert_nothing_left(db)
    assert run_init().exit_code == 0


def test_migration_refusal_is_reported_cleanly(write_init_rc, run_init, monkeypatch: pytest.MonkeyPatch) -> None:
    write_init_rc('state = "BW"\n')
    db = Path(os.environ["KOHLE_DB"])

    def refuse(staged: Path) -> str:
        raise RuntimeError("refused")

    monkeypatch.setattr(schema, "_upgrade_to_head", refuse)

    result = run_init()

    assert result.exit_code == 1
    assert "refused" in result.output
    assert "Traceback" not in result.output
    _assert_nothing_left(db)
