from kohle.core.result import Result
from kohle.domain.models import Operation
from kohle.infrastructure.transaction_context import DbTransactionContext


def _record_write(action: str):
    # A factory rather than one decorator per verb: they differ by this one
    # string, and hand-copied audit blocks drift apart.
    def decorator(fn):
        def wrapper(ctx: DbTransactionContext, *args, **kwargs):
            result = fn(ctx, *args, **kwargs)
            if result.is_ok:
                entity = result.unwrap()
                ctx.record_transaction_step(
                    Operation(
                        entity_type = entity.__tablename__,
                        entity_id = entity.id,
                        action = action,
                    )
                )
                return Result.ok(entity)
            return Result.err(result.unwrap_err())
        return wrapper
    return decorator


crud_create = _record_write("create")

# A soft delete is recorded as a delete rather than as an update to deleted_at:
# list-operations exists to say what happened, and "retired" is what happened.
crud_delete = _record_write("delete")


def crud_retrieve(fn):
    def wrapper(ctx: DbTransactionContext, *args, **kwargs):
        return fn(ctx, *args, **kwargs)
    return wrapper
