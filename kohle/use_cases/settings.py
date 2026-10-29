from collections.abc import Callable, Mapping
from dataclasses import dataclass

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    InvalidSettingValue,
    SettingError,
    UnknownSetting,
)
from kohle.domain.models import Setting
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.setting_services import (
    ledger_info_service,
    list_settings_service,
    set_setting_service,
)

Validator = Callable[[object], Result[str, InvalidSettingValue]]

# Ledger settings, in listing order. `init.toml` accepts `state` (bundesland.py)
# plus these.
SETTINGS: dict[str, Validator] = {}


def validate_settings(raw: Mapping[str, object]) -> Result[dict[str, str], SettingError]:
    validated: dict[str, str] = {}
    for key, value in raw.items():
        validator = SETTINGS.get(key)
        if validator is None:
            return Result.err(UnknownSetting(key, list(SETTINGS)))
        checked = validator(value)
        if checked.is_err:
            return Result.err(checked.unwrap_err())
        validated[key] = checked.unwrap()
    return Result.ok(validated)


@dataclass(frozen=True, slots=True)
class SettingsReport:
    ledger: str
    revision: str | None
    values: dict[str, str | None]


class ListSettings(UnitOfWork[SettingsReport, SettingError]):
    def execute(self) -> Result[SettingsReport, SettingError]:
        def use_case(ctx: DbTransactionContext) -> Result[SettingsReport, SettingError]:
            listed = list_settings_service(ctx)
            if listed.is_err:
                return Result.err(listed.unwrap_err())
            info = ledger_info_service(ctx)
            if info.is_err:
                return Result.err(info.unwrap_err())
            stored = {s.key: s.value for s in listed.unwrap()}
            values = {key: stored.get(key) for key in SETTINGS}
            return Result.ok(SettingsReport(info.unwrap().path, info.unwrap().revision, values))

        return self._run(use_case)


class SetSettings(UnitOfWork[list[Setting], SettingError]):
    def execute(self, values: Mapping[str, object]) -> Result[list[Setting], SettingError]:
        validated = validate_settings(values)
        if validated.is_err:
            return Result.err(validated.unwrap_err())

        def use_case(ctx: DbTransactionContext) -> Result[list[Setting], SettingError]:
            written: list[Setting] = []
            for key, value in validated.unwrap().items():
                res = set_setting_service(ctx, key, value)
                if res.is_err:
                    return Result.err(res.unwrap_err())
                written.append(res.unwrap())
            return Result.ok(written)

        return self._run(use_case)
