from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.domain_errors import SamplingError
from kohle.domain.models import SamplingRuleList
from kohle.infrastructure.crud import crud_create, crud_retrieve
from kohle.infrastructure.transaction_context import DbTransactionContext


@crud_retrieve
def current_rule_list_service(ctx: DbTransactionContext) -> Result[SamplingRuleList, SamplingError]:
    # .one(): every ledger at head has a row, seeded by the migration.
    def op(session: Session) -> SamplingRuleList:
        return session.query(SamplingRuleList).order_by(SamplingRuleList.id.desc()).limit(1).one()

    return ctx.run(op).map_err(lambda err: SamplingError(str(err)))


@crud_create
def _add_rule_list_service(ctx: DbTransactionContext, rules: str) -> Result[SamplingRuleList, SamplingError]:
    def op(session: Session) -> SamplingRuleList:
        row = SamplingRuleList(rules=rules)
        session.add(row)
        return row

    return ctx.run(op).map_err(lambda err: SamplingError(str(err)))


def set_rule_list_service(ctx: DbTransactionContext, rules: str) -> Result[SamplingRuleList, SamplingError]:
    """Append `rules` as the current list. The current text writes nothing, so a
    replay leaves no OperationGroup."""
    current = current_rule_list_service(ctx)
    if current.is_err:
        return current
    if current.unwrap().rules == rules:
        return current
    return _add_rule_list_service(ctx, rules)
