from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from kohle.core.result import Result
from kohle.db.connection import ledger_url, make_engine, make_session_factory
from kohle.db.schema import build_ledger, check_schema
from kohle.domain.domain_errors import (
    InitFileError,
    MissingInitKeys,
    SettingDiffers,
    SettingError,
    StartStateDiffers,
    StateError,
    UnknownInitKey,
)
from kohle.domain.models import START
from kohle.infrastructure.infra_errors import LedgerError
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.setting_services import set_setting_service
from kohle.services.state_services import put_state_entry_service
from kohle.use_cases.bundesland import ListStates, validate_state
from kohle.use_cases.settings import SETTINGS, ListSettings


@dataclass(frozen=True, slots=True)
class Initialized:
    path: Path
    revision: str
    created: bool


InitError = LedgerError | SettingError | StateError


@dataclass(frozen=True, slots=True)
class InitFile:
    state: str
    settings: dict[str, str]  # SETTINGS keys; none today


def validate_init_file(raw: Mapping[str, object]) -> Result[InitFile, InitFileError | StateError | SettingError]:
    # Unknown keys are reported before missing ones so a typo (`stat`) says
    # "unknown key" rather than "missing state".
    validated: dict[str, str] = {}
    for key, value in raw.items():
        if key == "state":
            checked = validate_state(value)
        elif key in SETTINGS:
            checked = SETTINGS[key](value)
        else:
            return Result.err(UnknownInitKey(key, ["state", *SETTINGS]))
        if checked.is_err:
            return Result.err(checked.unwrap_err())
        validated[key] = checked.unwrap()
    missing = [key for key in ["state", *SETTINGS] if key not in raw]
    if missing:
        return Result.err(MissingInitKeys(missing))
    return Result.ok(InitFile(validated.pop("state"), validated))


class PopulateLedger(UnitOfWork[None, InitError]):
    def execute(self, init: InitFile) -> Result[None, InitError]:
        def use_case(ctx: DbTransactionContext) -> Result[None, InitError]:
            put = put_state_entry_service(ctx, START, init.state)
            if put.is_err:
                return Result.err(put.unwrap_err())
            for key, value in init.settings.items():
                res = set_setting_service(ctx, key, value)
                if res.is_err:
                    return Result.err(res.unwrap_err())
            return Result.ok(None)

        return self._run(use_case)


def _compare_existing(path: Path, init: InitFile) -> Result[Initialized, InitError]:
    """Reads only: init never changes an existing ledger. The state is compared
    with the `start` entry, never with the state in force today."""
    engine = make_engine(ledger_url(path, "writer"))
    try:
        checked = check_schema(path, engine)
        if checked.is_err:
            return Result.err(checked.unwrap_err())
        make_session = make_session_factory(engine)
        states = ListStates(make_session()).execute()
        if states.is_err:
            return Result.err(states.unwrap_err())
        start = next((e for e in states.unwrap() if e.effective_from == START), None)
        if start is None or start.state != init.state:
            return Result.err(StartStateDiffers(path, start.state if start else None, init.state))
        listed = ListSettings(make_session()).execute()
        if listed.is_err:
            return Result.err(listed.unwrap_err())
        report = listed.unwrap()
        for key, wanted in init.settings.items():
            if report.values[key] != wanted:
                return Result.err(SettingDiffers(path, key, report.values[key], wanted))
        return Result.ok(Initialized(path, checked.unwrap(), created=False))
    finally:
        engine.dispose()


def init_ledger(path: Path, init: InitFile) -> Result[Initialized, InitError]:
    """`init` must come from `validate_init_file`. This use case opens
    its own engines rather than receiving a Session: deciding which file to
    open, the real one or a staged one, is its job."""
    if path.exists():
        return _compare_existing(path, init)

    def populate(make_session: sessionmaker[Session]) -> Result[None, InitError]:
        return PopulateLedger(make_session()).execute(init)

    built = build_ledger(path, copy_existing=False, populate=populate)
    return built.map(lambda revision: Initialized(path, revision, created=True))
