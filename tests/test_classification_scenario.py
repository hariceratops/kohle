"""Layer 3 — the spec's primary acceptance scenario, end to end.

The worked scenario from dev/specs/expense-classification.md, in the shape of
test_cash_envelope_scenario.py: rules classify most of a statement, one line
falls through, it is found and corrected, and the ledger reflects all of it.

If this passes, issues 013 through 017 are done.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issues 013-017")
def test_classification_scenario() -> None:
    # TODO(013-017) — the scenario, in order:
    #   1. add-rule for a couple of payees against leaf expense accounts
    #   2. import a statement whose rows carry counterparty name and IBAN,
    #      one of which matches no rule
    #   3. the matched rows land on their target accounts; the unmatched one
    #      lands in Unclassified Expense
    #   4. list-unclassified shows exactly that one line, with enough to write
    #      a rule from it
    #   5. reclassify it onto a leaf expense account
    #   6. balance reflects the correction on both accounts, and
    #      list-unclassified is now empty — with no change to its query
    #   7. the whole import is one operation group; the reclassify is another
    raise NotImplementedError
