from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.db.schema import stored_revision
from kohle.domain.domain_errors import SettingError
from kohle.domain.models import Setting
from kohle.infrastructure.crud import crud_create, crud_retrieve, crud_update
from kohle.infrastructure.transaction_context import DbTransactionContext


@dataclass(frozen=True, slots=True)
class LedgerInfo:
    path: str
    revision: str | None


@crud_retrieve
def list_settings_service(ctx: DbTransactionContext) -> Result[list[Setting], SettingError]:
    def op(session: Session) -> list[Setting]:
        return session.query(Setting).order_by(Setting.id).all()

    return ctx.run(op).map_err(lambda err: SettingError(str(err)))


@crud_create
def _create_setting_service(
    ctx: DbTransactionContext, key: str, value: str
) -> Result[Setting, SettingError]:
    def op(session: Session) -> Setting:
        setting = Setting(key=key, value=value)
        session.add(setting)
        return setting

    return ctx.run(op).map_err(lambda err: SettingError(str(err)))


@crud_update
def _update_setting_service(
    ctx: DbTransactionContext, setting_id: int, value: str
) -> Result[Setting, SettingError]:
    def op(session: Session) -> Setting:
        setting = session.get_one(Setting, setting_id)
        setting.value = value
        return setting

    return ctx.run(op).map_err(lambda err: SettingError(str(err)))


def set_setting_service(
    ctx: DbTransactionContext, key: str, value: str
) -> Result[Setting, SettingError]:
    """Create the key's row the first time, update it after. An identical
    value writes nothing, so a replay leaves no OperationGroup."""
    listed = list_settings_service(ctx)
    if listed.is_err:
        return Result.err(listed.unwrap_err())
    existing = next((s for s in listed.unwrap() if s.key == key), None)
    if existing is None:
        return _create_setting_service(ctx, key, value)
    if existing.value == value:
        return Result.ok(existing)
    return _update_setting_service(ctx, existing.id, value)


@crud_retrieve
def ledger_info_service(ctx: DbTransactionContext) -> Result[LedgerInfo, SettingError]:
    def op(session: Session) -> LedgerInfo:
        # The file SQLite actually opened ('' for an in-memory database).
        rows = session.execute(text("PRAGMA database_list")).all()
        path = next(row[2] for row in rows if row[1] == "main")
        return LedgerInfo(path, stored_revision(session.connection()))

    return ctx.run(op).map_err(lambda err: SettingError(str(err)))
