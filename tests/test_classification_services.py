"""Layer 2 — service tests against the `session` fixture.

The classification record (issues 015, 016, 017).

The predicate `unclassified_classifications_service` uses is the one the spec
gets wrong: it offers `matched_rule_id IS NULL` and `final_account_id IN
(buckets)` as equivalent, and they diverge permanently once a fall-through row
is corrected. dev/design/expense-classification.md §6.1 chooses the second,
which is also why issue 016 needs no code change when 017 lands.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 015")
def test_classification_services() -> None:
    # TODO(015) — one test per site:
    #   - add_classification_service writes proposed, matched rule, final and
    #     corrected for a matched row
    #   - and for a fall-through row, with matched_rule_id NULL and proposed
    #     equal to the bucket — one place to read from either way
    #   - UniqueConstraint(journal_entry_id): a second classification for the
    #     same entry is rejected, so "the classification of this line" has one
    #     referent (§2.2)

    # TODO(016) — unclassified_classifications_service returns rows whose
    #   final_account_id is a bucket; a matched row is absent.

    # TODO(017) — set_classification_outcome_service moves final_account_id
    #   and sets corrected, leaving proposed_account_id and matched_rule_id
    #   as they were: they are the record of what the engine got wrong.
    #   A corrected fall-through row then drops out of the unclassified
    #   query even though matched_rule_id is still NULL (§6.1).
    raise NotImplementedError
