from click.testing import CliRunner
from sqlalchemy import func

from kohle.app.cli.cli import cli
from kohle.domain.domain_errors import (
    InvalidSettingValue,
    MissingSettings,
    UnknownSetting,
)
from kohle.domain.models import Operation, OperationGroup, Setting
from kohle.use_cases.sampling import STATES
from kohle.use_cases.settings import (
    SETTINGS,
    ListSettings,
    SetSettings,
    validate_init_settings,
    validate_settings,
)


def test_state_accepts_every_bundesland_code() -> None:
    for code in STATES:
        assert validate_settings({"state": code}).unwrap() == {"state": code}


def test_state_rejects_other_codes_case_and_types() -> None:
    for bad in ("XX", "by", "", 1, None, ["BY"]):
        err = validate_settings({"state": bad}).unwrap_err()
        assert isinstance(err, InvalidSettingValue)
        assert str(err).endswith(f"expected one of {', '.join(STATES)}")


def test_unknown_key_lists_the_known_keys() -> None:
    err = validate_settings({"foo": "x"}).unwrap_err()

    assert isinstance(err, UnknownSetting)
    assert err.known == list(SETTINGS)


def test_init_validation_requires_every_registered_key() -> None:
    err = validate_init_settings({}).unwrap_err()

    assert isinstance(err, MissingSettings)
    assert err.keys == ["state"]


def test_init_validation_reports_unknown_before_missing() -> None:
    assert isinstance(validate_init_settings({"stat": "BW"}).unwrap_err(), UnknownSetting)


def test_list_settings_shows_unset_keys(session_factory) -> None:
    report = ListSettings(session_factory()).execute().unwrap()

    assert report.values == {"state": None}
    assert report.ledger == ""
    assert report.revision is None


def test_set_settings_stores_and_audits(session_factory) -> None:
    SetSettings(session_factory()).execute({"state": "HE"}).unwrap()

    report = ListSettings(session_factory()).execute().unwrap()
    assert report.values == {"state": "HE"}
    with session_factory() as s:
        ops = s.query(Operation).all()
        assert [(o.entity_type, o.action, o.group_id) for o in ops] == [("settings", "create", 1)]


def test_reading_settings_leaves_no_operation_group(session_factory) -> None:
    ListSettings(session_factory()).execute().unwrap()

    with session_factory() as s:
        assert s.query(func.count(OperationGroup.id)).scalar() == 0


def test_invalid_set_writes_nothing(session_factory) -> None:
    assert SetSettings(session_factory()).execute({"state": "XX"}).is_err

    with session_factory() as s:
        assert s.query(func.count(Setting.id)).scalar() == 0
        assert s.query(func.count(Operation.id)).scalar() == 0


def test_list_settings_command_prints_unset(session_factory) -> None:
    result = CliRunner().invoke(cli, ["list-settings"], obj=session_factory)

    assert result.exit_code == 0
    assert "state = (unset)" in result.output
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
    result = runner.invoke(cli, ["set-setting", "state", "HE"], obj=session_factory)

    assert result.exit_code == 0
    assert "Set state to HE" in result.output
    listed = runner.invoke(cli, ["list-settings"], obj=session_factory)
    assert "state = HE" in listed.output


def test_set_setting_audits_create_then_update_in_new_group(session_factory) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["set-setting", "state", "HE"], obj=session_factory)
    runner.invoke(cli, ["set-setting", "state", "BY"], obj=session_factory)

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
    runner.invoke(cli, ["set-setting", "state", "HE"], obj=session_factory)
    before = _counts(session_factory)

    result = runner.invoke(cli, ["set-setting", "state", "HE"], obj=session_factory)

    assert result.exit_code == 0
    assert _counts(session_factory) == before


def test_set_setting_unknown_key_changes_nothing(session_factory) -> None:
    result = CliRunner().invoke(cli, ["set-setting", "foo", "x"], obj=session_factory)

    assert result.exit_code == 1
    assert "known settings: state" in result.output
    assert _counts(session_factory) == (0, 0, 0)


def test_set_setting_invalid_value_changes_nothing(session_factory) -> None:
    result = CliRunner().invoke(cli, ["set-setting", "state", "XX"], obj=session_factory)

    assert result.exit_code == 1
    assert ", ".join(STATES) in result.output
    assert _counts(session_factory) == (0, 0, 0)
