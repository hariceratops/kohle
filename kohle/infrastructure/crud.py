from kohle.core.result import Result
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.domain.models import Operation


def crud_create(fn):
    def wrapper(ctx: DbTransactionContext, *args, **kwargs):
        result = fn(ctx, *args, **kwargs)
        if result.is_ok:
            entity = result.unwrap()
            ctx.record_transaction_step(
                Operation(
                    group_id = ctx.transaction_group.id,
                    entity_type = entity.__tablename__,
                    entity_id = entity.id,
                    action = "create",
                )
            )
            return Result.ok(entity)
        return Result.err(result.unwrap_err())
    return wrapper


def crud_retrieve(fn):
    def wrapper(ctx: DbTransactionContext, *args, **kwargs):
        return fn(ctx, *args, **kwargs)
    return wrapper
