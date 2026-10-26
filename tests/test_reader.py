"""Issues 060 and 061: `ledger.mode`, read-only open, and write refusal on a reader."""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from kohle.app.cli.cli import cli
from kohle.db.connection import ledger_url
from kohle.db.schema import open_ledger
from kohle.domain.models import AccountType
from kohle.use_cases.accounts import AddAccount


def _invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


@pytest.fixture
def live(write_init_rc, run_init) -> Path:
    write_init_rc('state = "BW"\n')
    db = Path(os.environ["KOHLE_DB"])
    assert run_init().exit_code == 0
    for args in (
        ["add-account", "Cash", "--type", "asset"],
        ["add-account", "Groceries"],
        ["record", "2026-03-01", "Aldi", "80", "--from", "Cash", "--to", "Groceries"],
    ):
        result = _invoke(*args)
        assert result.exit_code == 0, result.output
    return db


@pytest.fixture
def reader(live: Path, tmp_path: Path, write_config, monkeypatch) -> Path:
    copy = tmp_path / "copy" / "kohle.db"
    copy.parent.mkdir()
    assert _invoke("snapshot", str(copy)).exit_code == 0
    monkeypatch.setenv("KOHLE_DB", str(copy))
    write_config('ledger.mode = "reader"\n')
    return copy


def _stat(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


def test_list_config_shows_ledger_mode_default_and_file(reader: Path, tmp_path: Path) -> None:
    assert "ledger.mode = reader  (file)\n" in _invoke("list-config").output

    (tmp_path / "xdg-config" / "kohle" / "config.toml").unlink()

    assert "ledger.mode = writer  (default)\n" in _invoke("list-config").output


def test_get_config_ledger_mode(reader: Path) -> None:
    result = _invoke("get-config", "ledger.mode")

    assert result.exit_code == 0, result.output
    assert result.output == "reader\n"


def test_table_form_of_ledger_mode_is_equivalent(reader: Path, write_config) -> None:
    dotted = _invoke("list-config").output
    write_config('[ledger]\nmode = "reader"\n')

    assert _invoke("list-config").output == dotted


def test_invalid_ledger_mode_stops_commands_but_not_help(write_config) -> None:
    config = write_config('ledger.mode = "Reader"\n')

    result = _invoke("list-accounts")

    assert result.exit_code == 1
    assert result.output == f"Error: {config}: invalid ledger.mode 'Reader'; expected one of writer, reader\n"
    for args in (["--help"], ["list-accounts", "--help"]):
        assert _invoke(*args).exit_code == 0


def test_reads_work_on_a_reader_and_leave_the_copy_unchanged(live: Path, reader: Path, write_config) -> None:
    commands = (["balance", "Cash"], ["list-accounts"], ["net-worth"], ["list-settings"])
    write_config("")
    expected = [_invoke(*c).output for c in commands]
    write_config('ledger.mode = "reader"\n')
    before = _stat(reader)

    for command, want in zip(commands, expected, strict=True):
        result = _invoke(*command)
        assert result.exit_code == 0, result.output
        assert result.output == want

    assert _stat(reader) == before


def test_reader_url_is_read_only(reader: Path) -> None:
    assert ledger_url(reader, "reader").endswith("?mode=ro&uri=true")
    assert ledger_url(reader, "writer").endswith("?mode=rw&uri=true")

    session = open_ledger(reader, "reader").unwrap()()
    result = AddAccount(session).execute("Savings", AccountType.asset)

    assert result.is_err
    assert "readonly" in str(result.unwrap_err())
    assert "Savings" not in _invoke("list-accounts").output


def test_missing_file_on_a_reader_fails_without_init_hint(tmp_path: Path, write_config, monkeypatch) -> None:
    missing = tmp_path / "nowhere" / "kohle.db"
    monkeypatch.setenv("KOHLE_DB", str(missing))
    write_config('ledger.mode = "reader"\n')

    result = _invoke("list-accounts")

    assert result.exit_code == 1
    assert "this device is configured as a reader and never creates one" in result.output
    assert "kohle-cli init" not in result.output
    assert not missing.parent.exists()


def test_any_file_opens_read_only_not_only_snapshots(live: Path, write_config) -> None:
    writer_output = _invoke("balance", "Cash").output
    write_config('ledger.mode = "reader"\n')
    before = _stat(live)

    result = _invoke("balance", "Cash")

    assert result.exit_code == 0, result.output
    assert result.output == writer_output
    assert _stat(live) == before


def test_every_write_command_is_refused_on_a_reader() -> None:
    pytest.skip("TODO: parametrised over _WRITE_ARGV; exit 1; exact reader message; no 'readonly'; copy bytes unchanged")


def test_write_argv_covers_exactly_the_write_commands() -> None:
    pytest.skip('TODO: keys equal {n for n, c in cli.commands.items() if c.writes}')


def test_refusal_comes_before_plugins_load() -> None:
    pytest.skip('TODO: fetch-prices and import-statement with plugin loaders patched to raise still give the reader message')


def test_init_on_a_reader_creates_nothing() -> None:
    pytest.skip('TODO: reader message, nothing created')


def test_injected_factory_write_is_refused() -> None:
    pytest.skip('TODO: add-account with obj=session_factory: zero Account and OperationGroup rows')


def test_every_read_command_runs_on_a_reader() -> None:
    pytest.skip('TODO: parametrised over _READ_ARGV (snapshot included); exit 0; copy bytes unchanged')


def test_read_argv_covers_exactly_the_read_commands() -> None:
    pytest.skip('TODO: keys equal the writes=False commands')


def test_report_commands_are_not_writes() -> None:
    pytest.skip('TODO: balance, net-worth, positions, realised, net-worth-history are writes=False (039)')


def test_explicit_writer_mode_behaves_as_before() -> None:
    pytest.skip('TODO: ledger.mode = "writer": add-account succeeds')


def test_writes_flag_is_required() -> None:
    pytest.skip('TODO: _KohleCommand("x") raises TypeError')


def test_end_to_end_writer_to_reader() -> None:
    pytest.skip('TODO: record on the writer, snapshot, reader prints the same balance and refuses add-account')
