"""Layer 2 — service tests against the `session` fixture.

Rule persistence (issue 014). The ordering `list_rules_service` returns is
load-bearing: `compile_rules` preserves it rather than re-sorting, so
evaluation order is a property of this query.

`remove_rule_service` is a soft delete, and not stylistically —
dev/design/expense-classification.md §4.3 records why a hard delete is
unavailable and why ON DELETE SET NULL would be worse than either.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 014")
def test_rule_services() -> None:
    # TODO(014) — one test per site:
    #   - list_rules_service orders by priority ASC, then id ASC (§2.3)
    #   - a retired rule is absent from list_rules_service
    #   - remove_rule_service sets deleted_at rather than deleting the row;
    #     this is the first code in the codebase to write Archivable.deleted_at
    #   - a retired rule's id still resolves, so classifications that named it
    #     keep their record of what fired (§4.3)
    raise NotImplementedError
