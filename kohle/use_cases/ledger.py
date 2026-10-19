from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from kohle.core.result import Result
from kohle.db.schema import build_ledger
from kohle.domain.domain_errors import SettingError
from kohle.domain.models import Setting
from kohle.infrastructure.infra_errors import LedgerError, LedgerExists
from kohle.use_cases.settings import SetSettings


@dataclass(frozen=True, slots=True)
class Initialized:
    path: Path
    revision: str
    created: bool


InitError = LedgerError | SettingError


def init_ledger(path: Path, settings: Mapping[str, str]) -> Result[Initialized, InitError]:
    """`settings` must come from `validate_init_settings`. This use case opens
    its own engines rather than receiving a Session: deciding which file to
    open, the real one or a staged one, is its job."""
    if path.exists():
        return Result.err(LedgerExists(path))

    def populate(make_session: sessionmaker[Session]) -> Result[list[Setting], SettingError]:
        return SetSettings(make_session()).execute(settings)

    built = build_ledger(path, populate)
    return built.map(lambda revision: Initialized(path, revision, created=True))
