"""Issues 055 and 056: the device config file and its `ledger.path` key."""

import pytest


@pytest.mark.skip(reason="055: not implemented")
def test_ledger_path_validator_accepts_expands_and_rejects() -> None:
    # TODO(055): /abs/kohle.db accepted; ~/k.db expanded; kohle.db, "", 1, {}
    # and ~nosuchuser/k.db rejected with the expected text (design 15.2).
    ...


@pytest.mark.skip(reason="055: not implemented")
def test_table_form_and_dotted_form_load_equal() -> None:
    # TODO(055): [ledger] path = "/x" and ledger.path = "/x" give equal values.
    ...


@pytest.mark.skip(reason="055: not implemented")
def test_ledger_resolution_order_end_to_end() -> None:
    # TODO(055): file only uses the file; KOHLE_DB wins over the file; neither
    # uses the XDG default; KOHLE_DB="" counts as unset (design 15.2).
    ...


@pytest.mark.skip(reason="055: not implemented")
def test_missing_config_file_runs_with_defaults() -> None:
    # TODO(055)
    ...


@pytest.mark.skip(reason="055: not implemented")
def test_ledger_path_naming_a_missing_file_gives_the_no_ledger_error() -> None:
    # TODO(055)
    ...


@pytest.mark.skip(reason="055: not implemented")
def test_alembic_env_uses_ledger_path_and_names_the_file_on_a_bad_value() -> None:
    # TODO(055): command.upgrade at ledger.path; invalid path -> CommandError.
    ...


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
