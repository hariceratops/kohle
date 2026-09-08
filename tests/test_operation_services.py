from sqlalchemy.orm import Session

from kohle.domain.models import Operation, OperationGroup
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.operation_services import list_operations_service


def test_list_operations_orders_by_group_desc_then_id_asc(session: Session) -> None:
    group1 = OperationGroup()
    group2 = OperationGroup()
    session.add_all([group1, group2])
    session.flush()

    op1 = Operation(group_id=group1.id, entity_type="accounts", entity_id=1, action="create")
    op2 = Operation(group_id=group1.id, entity_type="journal_entries", entity_id=1, action="create")
    op3 = Operation(group_id=group2.id, entity_type="accounts", entity_id=2, action="create")
    session.add_all([op1, op2, op3])
    session.commit()

    ctx = DbTransactionContext(session)
    result = list_operations_service(ctx)

    assert result.is_ok
    ops = result.unwrap()
    # group2 (later) before group1 (earlier); within group1, steps in the
    # order they happened (op1's id precedes op2's id).
    assert [op.id for op in ops] == [op3.id, op1.id, op2.id]
