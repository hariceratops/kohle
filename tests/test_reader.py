"""Issues 060 and 061: `ledger.mode`, read-only open, and write refusal on a reader.

TODO: a `reader` fixture builds the live ledger, runs `snapshot` into
`tmp_path / "copy" / "kohle.db"`, points KOHLE_DB at the copy and writes
`ledger.mode = "reader"` with `write_config`."""
import pytest


def test_list_config_shows_ledger_mode_default_and_file() -> None:
    pytest.skip('TODO: writer (default) with no file; reader (file) with the fixture')


def test_get_config_ledger_mode() -> None:
    pytest.skip('TODO: prints reader')


def test_table_form_of_ledger_mode_is_equivalent() -> None:
    pytest.skip('TODO: [ledger] mode = "reader" equals the dotted form')


def test_invalid_ledger_mode_stops_commands_but_not_help() -> None:
    pytest.skip('TODO: list-accounts exit 1 naming file, ledger.mode and writer, reader; --help exit 0')


def test_reads_work_on_a_reader_and_leave_the_copy_unchanged() -> None:
    pytest.skip('TODO: balance, list-accounts, net-worth, list-settings; bytes and mtime unchanged')


def test_reader_url_is_read_only() -> None:
    pytest.skip('TODO: ledger_url(p, "reader") ends in ?mode=ro&uri=true; AddAccount on open_ledger(copy, "reader") returns Err containing readonly')


def test_missing_file_on_a_reader_fails_without_init_hint() -> None:
    pytest.skip('TODO: exit 1, reader wording, no `kohle-cli init`, nothing created')


def test_any_file_opens_read_only_not_only_snapshots() -> None:
    pytest.skip('TODO: live ledger with mode reader reads; bytes unchanged')


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
