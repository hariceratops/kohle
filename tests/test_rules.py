"""Layer 3 — use-case tests against the `session` fixture.

`AddRule`, `ListRules` and `RemoveRule` (issue 014).

The pattern is compiled when the rule is created, not when an import later
runs it. That is issue 014's acceptance criterion and the whole reason
dev/design/expense-classification.md §2.1 chose regexes over substrings: a
malformed pattern has to be rejectable at creation, and every string is a
valid substring pattern.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 014")
def test_rule_use_cases() -> None:
    # TODO(014) — one test per site:
    #   - AddRule rejects a malformed pattern at creation with
    #     InvalidRulePattern, and the message names the offending position —
    #     the criterion is a test, not a prose claim (§11)
    #   - AddRule rejects an unknown account name
    #   - AddRule rejects a non-leaf account, via the existing leaf-only rule
    #   - AddRule defaults priority when none is given (§2.3)
    #   - RemoveRule retires a rule that has already classified lines, and
    #     those classifications still resolve their matched rule afterwards
    #   - RemoveRule on an unknown rule returns RuleNotFoundError
    raise NotImplementedError
