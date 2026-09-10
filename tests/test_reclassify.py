"""Layer 3 — use-case tests against the `session` fixture.

`Reclassify` (issue 017).

Correction is an adjusting entry; the original entry is never edited, voided
or deleted. The classification row, however, is updated — it is an annotation
about the ledger rather than part of it, which is the distinction
dev/design/expense-classification.md §7.2 draws to justify adding crud_update.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 017")
def test_reclassify() -> None:
    # TODO(017) — one test per site:
    #   - a reversing pair is posted through post_entry: the wrong account
    #     credited, the right one debited, for the original amount
    #   - the original entry is unchanged — same lines, same accounts
    #   - the classification's final account moves and corrected is set, while
    #     proposed and matched rule stay as they were
    #   - correcting a fall-through row works the same as correcting a wrong
    #     rule match
    #   - balances move: the wrong account no longer holds the amount, the
    #     right one does
    #   - an unknown entry id returns NoClassificationForEntry
    #   - an unknown target account, and a non-leaf target, are rejected
    #
    # TODO(017) — a double reclassify (bucket -> A -> B) lands the amount on B
    #   with A and the bucket both at zero. This is the §7.1 detail: the
    #   reversal comes out of final_account_id, not proposed_account_id, and
    #   the two differ from the second correction onward.
    raise NotImplementedError
