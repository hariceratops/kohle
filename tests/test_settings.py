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
