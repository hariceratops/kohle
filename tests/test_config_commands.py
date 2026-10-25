"""Issues 057 and 058: `list-config`, `get-config`, and the settings commands."""

import pytest


@pytest.mark.skip(reason="057: not implemented")
def test_list_config_shows_value_and_source() -> None:
    # TODO(057): default / file / KOHLE_DB suffixes; file footer with
    # (not found) when missing (design 15.4).
    ...


@pytest.mark.skip(reason="057: not implemented")
def test_list_config_works_without_a_reachable_ledger() -> None:
    # TODO(057): nonexistent ledger.path, behind and ahead ledgers, and
    # open_ledger monkeypatched to raise; no sqlite3.connect recorded.
    ...


@pytest.mark.skip(reason="057: not implemented")
def test_get_config_prints_only_the_value_and_rejects_unknown_keys() -> None:
    # TODO(057): exact path plus newline; `get-config nope` exits 1 and lists
    # ledger.path.
    ...


@pytest.mark.skip(reason="058: not implemented")
def test_list_settings_ledger_line_shows_its_source() -> None:
    # TODO(058): (KOHLE_DB) / (file) / (default); exactly `ledger:   (in memory)`
    # with an injected factory (design 15.5).
    ...


@pytest.mark.skip(reason="058: not implemented")
def test_set_setting_refuses_device_keys_and_writes_nothing() -> None:
    # TODO(058): exit 1, message names the config path, Setting / Operation /
    # OperationGroup counts unchanged.
    ...


@pytest.mark.skip(reason="058: not implemented")
def test_set_setting_for_ledger_keys_is_unchanged() -> None:
    # TODO(058): `set-setting foo x` lists state; `set-setting state HE` works.
    ...
