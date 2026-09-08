# [chore] Expose the operation audit trail on the CLI

Every write records `Operation` rows through the `crud_create` decorator, and
`ListOperations` exists as a working, tested use case — but nothing in the
CLI reaches it, so the audit trail cannot be read at all. This predates the
ledger rework; the rework made it more valuable by increasing what gets
written.

Independent of the other issues.

## Acceptance Criteria

- A CLI command lists recorded operations via the existing `ListOperations`
  use case; no new service or use case is written.
- Each row shows at least the group, the entity type, the entity id and the
  action.
- Operations are ordered so the most recent work is findable — state the
  chosen order.
- Output uses `tabulate`, matching the other listing commands.
- The command is read-only and creates no operations of its own.
