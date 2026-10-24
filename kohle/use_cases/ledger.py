from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from kohle.core.result import Result
from kohle.db.connection import ledger_url, make_engine, make_session_factory
from kohle.db.schema import build_ledger, check_schema
from kohle.domain.domain_errors import SettingDiffers, SettingError
from kohle.domain.models import Setting
from kohle.infrastructure.infra_errors import LedgerError
from kohle.use_cases.settings import ListSettings, SetSettings


@dataclass(frozen=True, slots=True)
class Initialized:
    path: Path
    revision: str
    created: bool


InitError = LedgerError | SettingError


def _compare_existing(path: Path, settings: Mapping[str, str]) -> Result[Initialized, InitError]:
    """Reads only: init never changes an existing ledger."""
    engine = make_engine(ledger_url(path))
    try:
        checked = check_schema(path, engine)
        if checked.is_err:
            return Result.err(checked.unwrap_err())
        listed = ListSettings(make_session_factory(engine)()).execute()
        if listed.is_err:
            return Result.err(listed.unwrap_err())
        report = listed.unwrap()
        for key, wanted in settings.items():
            if report.values[key] != wanted:
                return Result.err(SettingDiffers(path, key, report.values[key], wanted))
        return Result.ok(Initialized(path, checked.unwrap(), created=False))
    finally:
        engine.dispose()


def init_ledger(path: Path, settings: Mapping[str, str]) -> Result[Initialized, InitError]:
    """`settings` must come from `validate_init_settings`. This use case opens
    its own engines rather than receiving a Session: deciding which file to
    open, the real one or a staged one, is its job."""
    if path.exists():
        return _compare_existing(path, settings)

    def populate(make_session: sessionmaker[Session]) -> Result[list[Setting], SettingError]:
        return SetSettings(make_session()).execute(settings)

    built = build_ledger(path, copy_existing=False, populate=populate)
    return built.map(lambda revision: Initialized(path, revision, created=True))
