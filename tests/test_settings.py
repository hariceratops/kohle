import pytest
from click.testing import CliRunner
from sqlalchemy import func

from kohle.app.cli.cli import cli
from kohle.core.result import Result
from kohle.domain.domain_errors import InvalidSettingValue, UnknownSetting
from kohle.domain.models import Operation, OperationGroup, Setting
from kohle.use_cases import settings
from kohle.use_cases.settings import (
    SETTINGS,
    ListSettings,
    SetSettings,
    validate_settings,
)


def _colour(value: object) -> Result[str, InvalidSettingValue]:
    if value in ("red", "blue"):
        return Result.ok(str(value))
    return Result.err(InvalidSettingValue("colour", value, "one of red, blue"))


@pytest.fixture(autouse=True)
def _colour_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """The registry is empty after 069; a stand-in key keeps the settings
    mechanism under test until a later feature adds a real one."""
    monkeypatch.setitem(settings.SETTINGS, "colour", _colour)


def test_unknown_key_lists_the_known_keys() -> None:
    err = validate_settings({"foo": "x"}).unwrap_err()

    assert isinstance(err, UnknownSetting)
    assert err.known == list(SETTINGS)


def test_unknown_key_with_no_registered_keys_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(settings.SETTINGS, "colour")

    err = validate_settings({"foo": "x"}).unwrap_err()

    assert str(err) == "unknown setting 'foo'; there are no ledger settings"


def test_list_settings_shows_unset_keys(session_factory) -> None:
    report = ListSettings(session_factory()).execute().unwrap()

    assert report.values == {"colour": None}
    assert report.ledger == ""
    assert report.revision is None


def test_set_settings_stores_and_audits(session_factory) -> None:
    SetSettings(session_factory()).execute({"colour": "red"}).unwrap()

    report = ListSettings(session_factory()).execute().unwrap()
    assert report.values == {"colour": "red"}
    with session_factory() as s:
        ops = s.query(Operation).all()
        assert [(o.entity_type, o.action, o.group_id) for o in ops] == [("settings", "create", 1)]


def test_reading_settings_leaves_no_operation_group(session_factory) -> None:
    ListSettings(session_factory()).execute().unwrap()

    with session_factory() as s:
        assert s.query(func.count(OperationGroup.id)).scalar() == 0


def test_invalid_set_writes_nothing(session_factory) -> None:
    assert SetSettings(session_factory()).execute({"colour": "XX"}).is_err

    with session_factory() as s:
        assert s.query(func.count(Setting.id)).scalar() == 0
        assert s.query(func.count(Operation.id)).scalar() == 0


def test_list_settings_command_prints_unset(session_factory) -> None:
    result = CliRunner().invoke(cli, ["list-settings"], obj=session_factory)

    assert result.exit_code == 0
    assert "colour = (unset)" in result.output
    assert "ledger:   (in memory)" in result.output
    assert "revision: (none)" in result.output


def _counts(session_factory) -> tuple[int, int, int]:
    with session_factory() as s:
        return (
            s.query(func.count(Setting.id)).scalar(),
            s.query(func.count(Operation.id)).scalar(),
            s.query(func.count(OperationGroup.id)).scalar(),
        )


def test_set_setting_command_stores_and_lists(session_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["set-setting", "colour", "red"], obj=session_factory)

    assert result.exit_code == 0
    assert "Set colour to red" in result.output
    listed = runner.invoke(cli, ["list-settings"], obj=session_factory)
    assert "colour = red" in listed.output


def test_set_setting_audits_create_then_update_in_new_group(session_factory) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["set-setting", "colour", "red"], obj=session_factory)
    runner.invoke(cli, ["set-setting", "colour", "blue"], obj=session_factory)

    with session_factory() as s:
        ops = s.query(Operation).order_by(Operation.id).all()
        assert [(o.entity_type, o.action) for o in ops] == [
            ("settings", "create"),
            ("settings", "update"),
        ]
        assert ops[0].group_id != ops[1].group_id
    listed = runner.invoke(cli, ["list-operations"], obj=session_factory)
    assert listed.exit_code == 0
    assert "settings" in listed.output


def test_set_setting_identical_value_adds_no_group(session_factory) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["set-setting", "colour", "red"], obj=session_factory)
    before = _counts(session_factory)

    result = runner.invoke(cli, ["set-setting", "colour", "red"], obj=session_factory)

    assert result.exit_code == 0
    assert _counts(session_factory) == before


def test_set_setting_unknown_key_changes_nothing(session_factory) -> None:
    result = CliRunner().invoke(cli, ["set-setting", "foo", "x"], obj=session_factory)

    assert result.exit_code == 1
    assert "known settings: colour" in result.output
    assert _counts(session_factory) == (0, 0, 0)


def test_set_setting_invalid_value_changes_nothing(session_factory) -> None:
    result = CliRunner().invoke(cli, ["set-setting", "colour", "XX"], obj=session_factory)

    assert result.exit_code == 1
    assert "one of red, blue" in result.output
    assert _counts(session_factory) == (0, 0, 0)


def test_set_setting_state_points_to_move_state(session_factory) -> None:
    result = CliRunner().invoke(cli, ["set-setting", "state", "BY"], obj=session_factory)

    assert result.exit_code == 1
    assert "move-state --from" in result.output
    assert _counts(session_factory) == (0, 0, 0)
