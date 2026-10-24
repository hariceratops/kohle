import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from click.testing import CliRunner
from sqlalchemy import create_engine, text

from kohle.app.cli.cli import cli
from kohle.db.connection import make_engine, make_session_factory
from kohle.db.schema import HEAD_REVISION, alembic_config, check_schema
from kohle.use_cases.settings import ListSettings

BEHIND = "d4e7a8c15b92"


def _build(revision: str = "head") -> Path:
    db = Path(os.environ["KOHLE_DB"])
    db.parent.mkdir(parents=True, exist_ok=True)
    db.touch()
    command.upgrade(alembic_config(), revision)
    return db


def _set_revision(db: Path, revision: str) -> None:
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = :r"), {"r": revision})
    engine.dispose()


def _head() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def test_head_revision_is_pinned_to_alembics_head() -> None:
    assert HEAD_REVISION == _head()


def test_missing_ledger_gives_one_line_and_creates_nothing() -> None:
    db = Path(os.environ["KOHLE_DB"])

    result = CliRunner().invoke(cli, ["list-accounts"])

    assert result.exit_code == 1
    assert result.output == f"Error: no ledger at {db}; run `kohle-cli init`\n"
    assert not db.exists()
    assert not db.parent.exists()


@pytest.mark.parametrize("args", [["list-accounts"], ["add-account", "Cash", "--type", "asset"]])
def test_behind_ledger_points_to_migrate_for_reads_and_writes(args: list[str]) -> None:
    _build(BEHIND)

    result = CliRunner().invoke(cli, args)

    assert result.exit_code == 1
    assert result.output.count("\n") == 1
    assert f"is at revision {BEHIND}" in result.output
    assert "run `kohle-cli migrate`" in result.output
    assert "Traceback" not in result.output


def test_ledger_without_a_stored_revision_counts_as_behind() -> None:
    db = Path(os.environ["KOHLE_DB"])
    db.parent.mkdir(parents=True)
    db.touch()

    result = CliRunner().invoke(cli, ["list-accounts"])

    assert result.exit_code == 1
    assert "is at revision none" in result.output
    assert "kohle-cli migrate" in result.output


def test_ahead_ledger_says_to_upgrade_kohle() -> None:
    db = _build()
    _set_revision(db, "ffffffffffff")

    result = CliRunner().invoke(cli, ["list-accounts"])

    assert result.exit_code == 1
    assert result.output.count("\n") == 1
    assert "ffffffffffff" in result.output
    assert "upgrade kohle" in result.output
    assert "Traceback" not in result.output


def test_unreadable_file_gives_one_line_without_traceback() -> None:
    db = Path(os.environ["KOHLE_DB"])
    db.parent.mkdir(parents=True)
    db.write_bytes(b"this is not a sqlite database" * 50)

    result = CliRunner().invoke(cli, ["list-accounts"])

    assert result.exit_code == 1
    assert result.output.startswith(f"Error: cannot read ledger at {db}")
    assert "Traceback" not in result.output


def test_current_ledger_runs_the_command() -> None:
    _build()

    result = CliRunner().invoke(cli, ["list-accounts"])

    assert result.exit_code == 0, result.output
    assert "People" in result.output


def test_check_covers_commands_that_never_touch_the_ledger() -> None:
    result = CliRunner().invoke(cli, ["list-importer-plugins"])

    assert result.exit_code == 1
    assert "no ledger at" in result.output


def test_a_stale_head_constant_falls_back_to_alembics_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    _build()
    monkeypatch.setattr("kohle.db.schema.HEAD_REVISION", "000000000000")

    assert CliRunner().invoke(cli, ["list-accounts"]).exit_code == 0

    _set_revision(Path(os.environ["KOHLE_DB"]), BEHIND)
    result = CliRunner().invoke(cli, ["list-accounts"])
    assert "kohle-cli migrate" in result.output


def test_help_needs_no_ledger_and_creates_nothing() -> None:
    db = Path(os.environ["KOHLE_DB"])
    runner = CliRunner()

    for args in (["--help"], ["list-accounts", "--help"], ["add-account", "--help"]):
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, result.output

    assert not db.parent.exists()


def test_check_succeeds_on_a_read_only_connection() -> None:
    db = _build()
    ro_url = f"sqlite:///file:{db}?mode=ro&uri=true"

    checked = check_schema(db, create_engine(ro_url))
    assert checked.unwrap() == _head()

    listed = ListSettings(make_session_factory(make_engine(ro_url))()).execute()
    assert listed.is_ok
    assert listed.unwrap().revision == _head()


def test_the_check_does_not_write() -> None:
    db = _build()
    before = (db.read_bytes(), db.stat().st_mtime_ns)

    assert CliRunner().invoke(cli, ["list-accounts"]).exit_code == 0

    assert (db.read_bytes(), db.stat().st_mtime_ns) == before
    assert not db.with_name(db.name + "-journal").exists()


def test_a_current_ledger_never_imports_alembic(tmp_path: Path) -> None:
    db = _build()
    script = textwrap.dedent(
        """
        import sys
        from click.testing import CliRunner
        from kohle.app.cli.cli import cli

        result = CliRunner().invoke(cli, ["list-accounts"])
        assert result.exit_code == 0, result.output
        assert "alembic" not in sys.modules, "alembic was imported"
        """
    )
    env = {**os.environ, "KOHLE_DB": str(db)}

    done = subprocess.run(
        [sys.executable, "-I", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
        check=False,
    )

    assert done.returncode == 0, done.stdout + done.stderr
