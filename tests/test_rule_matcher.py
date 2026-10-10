"""Layer 1 — pure unit tests, no fixture.

The rule matcher (issues 014, 015). `compile_rules` and `match_rule` hold
nearly every decision in dev/design/expense-classification.md §2.1 and §2.3 —
which pattern wins, what a pattern is matched against, and how ties resolve —
and none of them touches a session. The `Rule` instances here are plain
in-memory objects.

`_optional_str`, the other pure function this slice added, is covered in
test_classify_import.py beside the statement-cell shapes it normalises.
"""

from kohle.domain.models import Rule
from kohle.services.journal_services import Counterparty
from kohle.use_cases.rules import compile_rules, match_rule

NO_COUNTERPARTY = Counterparty(None, None)
IBAN = "DE89370400440532013000"


def _rules(*specs: tuple[int, str, int]) -> list[Rule]:
    """Rules in the order `list_rules_service` would return them."""
    return [Rule(id=rule_id, pattern=pattern, account_id=account_id) for rule_id, pattern, account_id in specs]


def test_first_match_wins_and_evaluation_stops_there() -> None:
    compiled = compile_rules(_rules((1, "REWE", 10), (2, "SAGT", 20)))

    matched = match_rule(compiled, "REWE SAGT DANKE", NO_COUNTERPARTY)

    # Both patterns hit this description; the earlier rule is the answer, which
    # is what makes matched_rule_id a single well-defined value.
    assert matched is not None
    assert (matched.rule_id, matched.account_id) == (1, 10)


def test_compile_rules_preserves_the_order_it_was_given() -> None:
    # REGRESSION: the ordering is the priority contract — list_rules_service
    # sorts by (priority, id) and the matcher takes the first hit, so sorting
    # or reordering here would silently change which rule wins.
    rules = _rules((7, "LIDL", 30), (2, "ALDI", 20), (5, "REWE", 10))

    assert [rule.rule_id for rule in compile_rules(rules)] == [7, 2, 5]


def test_equal_priority_rules_resolve_by_the_order_they_arrive_in() -> None:
    # Two rules matching the same line: whichever the service put first wins,
    # and the service breaks priority ties on id, which is a total order.
    by_id = compile_rules(_rules((3, "AMZN", 10), (9, "AMZN", 20)))

    matched = match_rule(by_id, "AMZN MKTPLACE", NO_COUNTERPARTY)

    assert matched is not None
    assert matched.rule_id == 3


def test_a_pattern_matches_any_one_field_on_its_own() -> None:
    compiled = compile_rules(_rules((1, "ALDI SUED", 10)))

    assert match_rule(compiled, "Card payment 4711", Counterparty("ALDI SUED", None)) is not None
    assert match_rule(compiled, "ALDI SUED Filiale 22", NO_COUNTERPARTY) is not None
    assert match_rule(compiled, "Card payment 4711", Counterparty("REWE", None)) is None


def test_an_anchored_iban_matches_the_iban_field_and_not_a_description() -> None:
    # This is what per-field matching buys over a concatenated haystack: ^ and
    # $ mean "this exact counterparty IBAN" rather than "start and end of the
    # blob", which is the highest-value rule shape for a bank ledger.
    compiled = compile_rules(_rules((1, f"^{IBAN}$", 10)))

    assert match_rule(compiled, "Rent", Counterparty("Landlord", IBAN)) is not None
    assert match_rule(compiled, f"Standing order to {IBAN}", NO_COUNTERPARTY) is None


def test_matching_is_case_insensitive_by_default() -> None:
    compiled = compile_rules(_rules((1, "rewe", 10)))

    assert match_rule(compiled, "REWE SAGT DANKE", NO_COUNTERPARTY) is not None
    assert match_rule(compiled, "Rewe Markt GmbH", NO_COUNTERPARTY) is not None


def test_an_inline_flag_restores_case_sensitivity() -> None:
    compiled = compile_rules(_rules((1, "(?-i:REWE)", 10)))

    assert match_rule(compiled, "REWE SAGT DANKE", NO_COUNTERPARTY) is not None
    assert match_rule(compiled, "Rewe Markt GmbH", NO_COUNTERPARTY) is None


def test_an_absent_counterparty_field_is_skipped_rather_than_matched() -> None:
    # A NULL counterparty is normal — an ATM withdrawal has no beneficiary —
    # and must not crash the import or count as a match.
    compiled = compile_rules(_rules((1, "ALDI", 10)))

    assert match_rule(compiled, "Cash withdrawal", NO_COUNTERPARTY) is None
    assert match_rule(compiled, "ALDI", NO_COUNTERPARTY) is not None


def test_an_empty_rule_set_matches_nothing() -> None:
    assert match_rule(compile_rules([]), "REWE SAGT DANKE", Counterparty("REWE", IBAN)) is None
