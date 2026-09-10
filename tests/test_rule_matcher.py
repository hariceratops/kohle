"""Layer 1 — pure unit tests, no fixture.

The rule matcher (issues 014, 015). `compile_rules` and `match_rule` hold
nearly every decision in dev/design/expense-classification.md §2.1 and §2.3 —
which pattern wins, what a pattern is matched against, and how ties resolve —
and none of them touches a session. The `Rule` instances here are plain
in-memory objects.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 014")
def test_rule_matcher() -> None:
    # TODO(014/015) — one test per site:
    #   - first match wins across a priority-ordered list; evaluation stops
    #   - equal priority ties break on id, not insertion order (§2.3)
    #   - a pattern matching description but not counterparty, and vice versa
    #   - an anchored IBAN pattern (^DE89...$) matches counterparty_iban
    #     exactly and does NOT match a description that merely contains it —
    #     this is what per-field matching buys over a concatenated blob (§2.1)
    #   - matching is case-insensitive by default
    #   - (?-i:...) restores case sensitivity within a pattern
    #   - a None field is skipped, not crashed on
    #   - an empty rule list returns None
    #   - compile_rules preserves the ordering the service returned; same
    #     class of guard as the ordered average-cost fold (§11)
    #   - _optional_str normalises pd.NA, NaN, '', '  ' and a normal string
    raise NotImplementedError
