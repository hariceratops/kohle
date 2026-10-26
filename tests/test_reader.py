"""Issues 060 and 061: `ledger.mode`, read-only open, and write refusal on a reader."""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import func, select

from kohle.app.cli.cli import _KohleCommand, cli
from kohle.db.connection import ledger_url
from kohle.db.schema import open_ledger
from kohle.domain.models import Account, AccountType, OperationGroup
from kohle.use_cases.accounts import AddAccount


STATEMENT = Path(__file__).parent / "fixtures" / "deutsche_bank_statement.csv"

_WRITE_ARGV: dict[str, list[str]] = {
    "init": ["init"],
    "migrate": ["migrate"],
    "set-setting": ["set-setting", "state", "BW"],
    "add-account": ["add-account", "Savings"],
    "add-unit": ["add-unit", "IE00B4L5Y983", "Core MSCI World"],
    "import-statement": ["import-statement", "deutsche-bank", "Cash", str(STATEMENT)],
    "record": ["record", "2026-03-02", "Rewe", "10", "--from", "Cash", "--to", "Groceries"],
    "record-split": ["record-split", "2026-03-02", "Rewe", "--line", "Cash:10:EUR:1:credit", "--line", "Groceries:10:EUR:1:debit"],
    "add-rule": ["add-rule", "ALDI", "Groceries"],
    "remove-rule": ["remove-rule", "1"],
    "reclassify": ["reclassify", "1", "Groceries"],
    "add-group": ["add-group", "Flat"],
    "split-line": ["split-line", "1", "--mine", "5", "--share", "Anna:5"],
    "unsplit-line": ["unsplit-line", "1"],
    "set-price-source": ["set-price-source", "IE00B4L5Y983", "alphavantage", "IWDA"],
    "fetch-prices": ["fetch-prices"],
}


def _read_argv(tmp_path: Path) -> dict[str, list[str]]:
    return {
        "list-config": ["list-config"],
        "get-config": ["get-config", "ledger.mode"],
        "snapshot": ["snapshot", str(tmp_path / "snap.db")],
        "list-settings": ["list-settings"],
        "list-accounts": ["list-accounts"],
        "list-child-accounts": ["list-child-accounts", "Groceries"],
        "list-units": ["list-units"],
        "list-importer-plugins": ["list-importer-plugins"],
        "entries-in-period": ["entries-in-period", "Cash", "2026-03-01", "2026-03-31"],
        "balance": ["balance", "Cash"],
        "list-operations": ["list-operations"],
        "list-rules": ["list-rules"],
        "list-unclassified": ["list-unclassified"],
        "who-owes-what": ["who-owes-what"],
        "net-worth": ["net-worth"],
        "positions": ["positions"],
        "realised": ["realised"],
        "settle-up": ["settle-up"],
        "net-worth-history": ["net-worth-history", "--state", "BW"],
    }


def _commands(writes: bool) -> set[str]:
    return {name for name, command in cli.commands.items() if command.writes is writes}


def _reader_message(config: Path) -> str:
    return f"Error: this device is configured as a reader; `ledger.mode` is set in {config}\n"


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


@pytest.fixture
def config_file(reader: Path, tmp_path: Path) -> Path:
    return tmp_path / "xdg-config" / "kohle" / "config.toml"


@pytest.mark.parametrize("name", sorted(_WRITE_ARGV))
def test_every_write_command_is_refused_on_a_reader(name: str, reader: Path, config_file: Path) -> None:
    before = _stat(reader)

    result = _invoke(*_WRITE_ARGV[name])

    assert result.exit_code == 1
    assert result.output == _reader_message(config_file)
    assert "readonly" not in result.output
    assert _stat(reader) == before


def test_write_argv_covers_exactly_the_write_commands() -> None:
    assert set(_WRITE_ARGV) == _commands(True)


def test_refusal_comes_before_plugins_load(reader: Path, config_file: Path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("plugins must not load on a reader")

    for name in ("load_price_plugins", "call_price_plugins", "load_plugins"):
        monkeypatch.setattr(f"kohle.app.cli.cli.{name}", boom)

    for name in ("fetch-prices", "import-statement"):
        result = _invoke(*_WRITE_ARGV[name])

        assert result.exit_code == 1
        assert result.output == _reader_message(config_file)


def test_init_on_a_reader_creates_nothing(tmp_path: Path, write_config, monkeypatch) -> None:
    missing = tmp_path / "nowhere" / "kohle.db"
    monkeypatch.setenv("KOHLE_DB", str(missing))
    config = write_config('ledger.mode = "reader"\n')

    result = _invoke("init")

    assert result.exit_code == 1
    assert result.output == _reader_message(config)
    assert not missing.parent.exists()


def test_injected_factory_write_is_refused(session, write_config) -> None:
    config = write_config('ledger.mode = "reader"\n')

    result = CliRunner().invoke(cli, ["add-account", "Savings"], obj=lambda: session)

    assert result.exit_code == 1
    assert result.output == _reader_message(config)
    assert session.scalar(select(func.count()).select_from(Account)) == 0
    assert session.scalar(select(func.count()).select_from(OperationGroup)) == 0


def test_every_read_command_runs_on_a_reader(reader: Path, tmp_path: Path) -> None:
    before = _stat(reader)

    for name, argv in _read_argv(tmp_path).items():
        result = _invoke(*argv)

        assert result.exit_code == 0, f"{name}: {result.output}"
    assert _stat(reader) == before


def test_read_argv_covers_exactly_the_read_commands(tmp_path: Path) -> None:
    assert set(_read_argv(tmp_path)) == _commands(False)


def test_report_commands_are_not_writes() -> None:
    assert {"balance", "net-worth", "positions", "realised", "net-worth-history"} <= _commands(False)


def test_explicit_writer_mode_behaves_as_before(live: Path, write_config) -> None:
    write_config('ledger.mode = "writer"\n')

    result = _invoke("add-account", "Savings")

    assert result.exit_code == 0, result.output
    assert "Savings" in _invoke("list-accounts").output


def test_writes_flag_is_required() -> None:
    with pytest.raises(TypeError):
        _KohleCommand("x")


def test_end_to_end_writer_to_reader(live: Path, tmp_path: Path, write_config, monkeypatch) -> None:
    balance = _invoke("balance", "Cash").output
    copy = tmp_path / "copy.db"
    assert _invoke("snapshot", str(copy)).exit_code == 0
    monkeypatch.setenv("KOHLE_DB", str(copy))
    config = write_config('ledger.mode = "reader"\n')

    assert _invoke("balance", "Cash").output == balance
    refused = _invoke("add-account", "Savings")
    assert refused.exit_code == 1
    assert refused.output == _reader_message(config)
