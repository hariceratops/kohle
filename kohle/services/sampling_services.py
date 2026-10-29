from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.domain_errors import SamplingError
from kohle.domain.models import SamplingRuleList
from kohle.infrastructure.crud import crud_retrieve
from kohle.infrastructure.transaction_context import DbTransactionContext


@crud_retrieve
def current_rule_list_service(ctx: DbTransactionContext) -> Result[SamplingRuleList, SamplingError]:
    # .one(): every ledger at head has a row, seeded by the migration.
    def op(session: Session) -> SamplingRuleList:
        return session.query(SamplingRuleList).order_by(SamplingRuleList.id.desc()).limit(1).one()

    return ctx.run(op).map_err(lambda err: SamplingError(str(err)))
