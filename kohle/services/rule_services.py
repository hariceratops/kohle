from datetime import UTC, datetime

from sqlalchemy.orm import Session, joinedload

from kohle.core.result import Result
from kohle.domain.domain_errors import RuleError, RuleNotFoundError
from kohle.domain.models import Rule
from kohle.infrastructure.crud import crud_create, crud_delete, crud_retrieve
from kohle.infrastructure.transaction_context import DbTransactionContext


@crud_create
def add_rule_service(
    ctx: DbTransactionContext, pattern: str, account_id: int, priority: int
) -> Result[Rule, RuleError]:
    def op(session: Session) -> Rule:
        rule = Rule(pattern=pattern, account_id=account_id, priority=priority)
        session.add(rule)
        return rule

    return ctx.run(op).map_err(lambda err: RuleError(str(err)))


@crud_retrieve
def list_rules_service(ctx: DbTransactionContext) -> Result[list[Rule], RuleError]:
    def op(session: Session) -> list[Rule]:
        return (
            session.query(Rule)
            # The unit of work closes the session before the caller sees these,
            # so anything the caller reads has to be loaded up front.
            .options(joinedload(Rule.account))
            .filter(Rule.deleted_at.is_(None))
            # This ordering is the evaluation contract, not presentation: the
            # matcher takes the first rule that hits and compiles the list
            # as-is. id breaks ties because it is a total order, which is what
            # makes two equal-priority rules resolve the same way on every run.
            .order_by(Rule.priority.asc(), Rule.id.asc())
            .all()
        )

    return ctx.run(op).map_err(lambda err: RuleError(str(err)))


@crud_delete
def remove_rule_service(ctx: DbTransactionContext, rule_id: int) -> Result[Rule, RuleError]:
    """Retire a rule, keeping its row.

    A hard delete is not available: PRAGMA foreign_keys is on, so SQLite
    refuses it for any rule a classification already names — that is, for every
    rule anyone would want to remove. ON DELETE SET NULL would be worse still,
    rewriting "rule 7 sent this here" into "no rule matched" undetectably. The
    surviving pattern text is what keeps a past correction interpretable.
    """

    def op(session: Session) -> Rule | None:
        rule = (
            session.query(Rule)
            .filter(Rule.id == rule_id, Rule.deleted_at.is_(None))
            .one_or_none()
        )
        if rule is not None:
            # Naive UTC, matching what Archivable.created_at defaults to: an
            # aware datetime in a naive column would compare and sort against
            # every existing timestamp inconsistently.
            rule.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        return rule

    return (
        ctx.run(op)
        .map_err(lambda err: RuleError(str(err)))
        .and_then(lambda rule:
            Result.ok(rule)
            if rule is not None
            else Result.err(RuleNotFoundError(rule_id))
        )
    )
