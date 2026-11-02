"""Layer 1 — the rule file parser and the planner (design §17.2)."""

import pytest

from kohle.use_cases.conditions import When
from kohle.use_cases.rules import (
    RULE_PRIORITY_STEP,
    FileRule,
    RuleFile,
    StoredRule,
    parse_rule_file,
    plan_rule_changes,
)

ACCOUNTS = {"Groceries": 1, "Rent": 2, "Household": 3}


def _error(text: str) -> str:
    result = parse_rule_file(text)
    assert result.is_err
    return str(result.unwrap_err())


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[[rule]]\naccount = "A"\n[rule.when]\nany_field = "x', "not valid TOML"),
        ('colour = "red"\n', "colour: is not a known key"),
        ("base = 5\n", "base: must be a string"),
        ("rule = 5\n", "rule: must be an array of tables"),
        ('[[rule]]\naccount = "A"\nid = 7\n[rule.when]\nany_field = "x"\n', "rule 1, id: is not a known key"),
        ('[[rule]]\n[rule.when]\nany_field = "x"\n', "rule 1, account: is required"),
        ('[[rule]]\naccount = ""\n[rule.when]\nany_field = "x"\n', "rule 1, account: must be a non-empty string"),
        ('[[rule]]\naccount = "A"\nnote = 3\n[rule.when]\nany_field = "x"\n', "rule 1, note: must be a string"),
        ('[[rule]]\naccount = "A"\n', "rule 1, when: is required"),
        ('[[rule]]\naccount = "A"\nwhen = {}\n', "rule 1, when: must be a table with at least one condition"),
        ('[[rule]]\naccount = "A"\n[rule.when]\nmerchant = "x"\n', "rule 1, when.merchant: is not a known condition"),
        ('[[rule]]\naccount = "A"\n[rule.when]\ndescription = "("\n', "rule 1, when.description: is not a valid pattern"),
        ('[[rule]]\naccount = "A"\n[rule.when]\ncounterparty = "  "\n', "rule 1, when.counterparty: must not be empty"),
        ('[[rule]]\naccount = "A"\n[rule.when]\niban = "DE.*"\n', "rule 1, when.iban: must be an IBAN"),
        ('[[rule]]\naccount = "A"\n[rule.when]\niban = 5\n', "rule 1, when.iban: must be a string"),
        ('[[rule]]\naccount = "A"\n[rule.when]\nany = []\n', "rule 1, when.any: must be a non-empty array"),
        ('[[rule]]\naccount = "A"\n[rule.when]\nnot = {}\n', "rule 1, when.not: must be a table with at least one"),
        (
            '[[rule]]\naccount = "A"\n[rule.when]\nany = [{ description = "x" }, {}]\n',
            "rule 1, when.any[2]: must be a table with at least one",
        ),
    ],
)
def test_every_rejection_names_the_rule_and_the_key(text: str, message: str) -> None:
    assert _error(text).startswith(message)


def test_a_syntax_error_carries_the_line() -> None:
    assert "(at line 2, column" in _error('[[rule]]\naccount = \n[rule.when]\nany_field = "x"\n')


def test_the_position_is_the_rules_place_in_the_file() -> None:
    text = (
        '[[rule]]\naccount = "A"\n[rule.when]\ndescription = "ok"\n'
        '[[rule]]\naccount = "A"\n[rule.when]\ndescription = "("\n'
    )

    assert _error(text).startswith("rule 2, when.description:")


def test_a_valid_file_parses_with_normalised_iban_and_no_note_for_an_empty_one() -> None:
    text = (
        'base = "abc"\n'
        '[[rule]]\naccount = "Rent"\nnote = ""\n[rule.when]\niban = "de89 3704"\ncounterparty = "Vermieter"\n'
    )

    parsed = parse_rule_file(text).unwrap()

    assert parsed == RuleFile(
        "abc", (FileRule(1, "Rent", None, When(counterparty="Vermieter", iban="DE893704")),)
    )


def test_a_file_with_any_and_not_in_either_layout_parses_to_the_same_rule() -> None:
    multiline = (
        '[[rule]]\naccount = "Groceries"\n[rule.when]\nany = [\n  { description = "rewe" },\n'
        '  { counterparty = "edeka", not = { description = "pfand" } },\n]\n'
    )
    sections = (
        '[[rule]]\naccount = "Groceries"\n'
        '[[rule.when.any]]\ndescription = "rewe"\n'
        '[[rule.when.any]]\ncounterparty = "edeka"\n[rule.when.any.not]\ndescription = "pfand"\n'
    )

    assert parse_rule_file(multiline).unwrap() == parse_rule_file(sections).unwrap()


def test_an_empty_file_is_an_empty_rule_set() -> None:
    assert parse_rule_file("").unwrap() == RuleFile(None, ())


def test_two_rules_with_identical_content_name_both_positions() -> None:
    text = (
        '[[rule]]\naccount = "A"\n[rule.when]\ndescription = "x"\niban = "DE1"\n'
        '[[rule]]\naccount = "B"\n[rule.when]\ndescription = "x"\n'
        '[[rule]]\naccount = "A"\n[rule.when]\niban = "de 1"\ndescription = "x"\n'
    )

    assert _error(text) == "rule 3: has the same account and conditions as rule 1"


def test_the_same_conditions_on_different_accounts_are_not_duplicates() -> None:
    text = (
        '[[rule]]\naccount = "A"\n[rule.when]\ndescription = "x"\n'
        '[[rule]]\naccount = "B"\n[rule.when]\ndescription = "x"\n'
    )

    assert parse_rule_file(text).is_ok


# --- the planner -----------------------------------------------------------


def _stored(rule_id: int, pattern: str, account: str = "Groceries", priority: int | None = None, note=None):
    return StoredRule(
        rule_id,
        priority if priority is not None else rule_id * RULE_PRIORITY_STEP,
        ACCOUNTS[account],
        account,
        When(any_field=pattern),
        note,
    )


def _file(*specs: tuple[str, str] | tuple[str, str, str | None]) -> RuleFile:
    """(pattern, account[, note]) in file order."""
    return RuleFile(
        None,
        tuple(
            FileRule(i, spec[1], spec[2] if len(spec) == 3 else None, When(any_field=spec[0]))
            for i, spec in enumerate(specs, start=1)
        ),
    )


def _plan(stored, file):
    return plan_rule_changes(stored, file, ACCOUNTS, "base")


def _order_after(stored, plan) -> list[str]:
    """Patterns in (priority, id) order once the plan is applied, with new
    rules given ids above every existing one, in file order."""
    next_id = max((r.rule_id for r in stored), default=0) + 1
    rows = []
    for item in plan.rules:
        if item.kept is not None:
            rows.append((item.priority, item.kept.rule_id, item.rule.when.any_field))
        else:
            rows.append((item.priority, next_id, item.rule.when.any_field))
            next_id += 1
    return [pattern for _, _, pattern in sorted(rows)]


def test_an_unchanged_set_gives_an_empty_plan() -> None:
    stored = [_stored(1, "A"), _stored(2, "B", "Rent")]

    plan = _plan(stored, _file(("A", "Groceries"), ("B", "Rent")))

    assert plan.is_empty
    assert plan.unchanged == 2
    assert plan.reordered == frozenset()
    assert plan.updates == ()


def test_an_unchanged_set_with_untidy_priorities_still_writes_nothing() -> None:
    stored = [_stored(1, "A", priority=100), _stored(2, "B", priority=100), _stored(3, "C", priority=7)]
    stored.sort(key=lambda r: (r.priority, r.rule_id))

    plan = _plan(stored, _file(("C", "Groceries"), ("A", "Groceries"), ("B", "Groceries")))

    assert plan.is_empty


def test_a_note_only_change_updates_the_note_and_keeps_the_id() -> None:
    stored = [_stored(1, "A"), _stored(2, "B")]

    plan = _plan(stored, _file(("A", "Groceries"), ("B", "Groceries", "why")))

    assert [p.kept.rule_id for p in plan.renoted] == [2]
    assert [(p.kept.rule_id, p.priority, p.rule.note) for p in plan.updates] == [(2, 200, "why")]
    assert plan.added == () and plan.retired == ()
    assert plan.unchanged == 1


def test_a_moved_rule_is_reordered_and_only_its_priority_changes() -> None:
    stored = [_stored(1, "A"), _stored(2, "B"), _stored(3, "C")]

    plan = _plan(stored, _file(("A", "Groceries"), ("C", "Groceries"), ("B", "Groceries")))

    assert len(plan.reordered) == 1
    assert plan.added == () and plan.retired == ()
    assert all(p.rule.note == p.kept.note for p in plan.updates)
    assert _order_after(stored, plan) == ["A", "C", "B"]


@pytest.mark.parametrize(("order", "moved"), [("BCDA", 1), ("DABC", 4)])
def test_moving_one_rule_to_the_far_end_reports_only_that_rule(order: str, moved: int) -> None:
    stored = [_stored(i, p) for i, p in enumerate("ABCD", start=1)]

    plan = _plan(stored, _file(*((p, "Groceries") for p in order)))

    assert plan.reordered == frozenset({moved})
    assert _order_after(stored, plan) == list(order)


def test_a_changed_condition_or_account_retires_the_old_rule_and_adds_a_new_one() -> None:
    stored = [_stored(1, "A"), _stored(2, "B"), _stored(3, "C")]

    plan = _plan(stored, _file(("A2", "Groceries"), ("B", "Rent"), ("C", "Groceries")))

    assert [r.rule_id for r in plan.retired] == [1, 2]
    assert [p.rule.when.any_field for p in plan.added] == ["A2", "B"]
    assert plan.unchanged == 1
    assert _order_after(stored, plan) == ["A2", "B", "C"]


def test_an_empty_file_retires_everything() -> None:
    stored = [_stored(1, "A"), _stored(2, "B")]

    plan = _plan(stored, RuleFile(None, ()))

    assert [r.rule_id for r in plan.retired] == [1, 2]
    assert plan.rules == () and not plan.is_empty


def test_legacy_stored_duplicates_keep_the_first_and_retire_the_second() -> None:
    stored = [_stored(1, "A"), _stored(2, "A")]

    plan = _plan(stored, _file(("A", "Groceries")))

    assert [p.kept.rule_id for p in plan.rules] == [1]
    assert [r.rule_id for r in plan.retired] == [2]


# --- priorities ------------------------------------------------------------


def test_inserts_at_the_front_middle_and_end_leave_kept_priorities_alone() -> None:
    stored = [_stored(1, "A"), _stored(2, "B")]

    plan = _plan(stored, _file(("F", "Groceries"), ("A", "Groceries"), ("M", "Groceries"), ("B", "Groceries"), ("E", "Groceries")))

    assert plan.updates == ()
    assert [(p.rule.when.any_field, p.priority) for p in plan.rules] == [
        ("F", 0), ("A", 100), ("M", 150), ("B", 200), ("E", 300),
    ]
    assert _order_after(stored, plan) == ["F", "A", "M", "B", "E"]


def test_several_inserts_into_one_gap_share_a_priority_and_stay_in_file_order() -> None:
    stored = [_stored(1, "A"), _stored(2, "B")]

    plan = _plan(stored, _file(("A", "Groceries"), ("X", "Groceries"), ("Y", "Groceries"), ("B", "Groceries")))

    assert plan.updates == ()
    assert _order_after(stored, plan) == ["A", "X", "Y", "B"]


def test_an_insert_between_tied_priorities_renumbers_and_updates_only_what_changed() -> None:
    stored = [_stored(1, "A", priority=100), _stored(2, "B", priority=100), _stored(3, "C", priority=300)]

    plan = _plan(stored, _file(("A", "Groceries"), ("N", "Groceries"), ("B", "Groceries"), ("C", "Groceries")))

    assert {p.kept.rule_id: p.priority for p in plan.updates} == {2: 300, 3: 400}
    assert plan.reordered == frozenset()
    assert plan.unchanged == 3
    assert _order_after(stored, plan) == ["A", "N", "B", "C"]


def test_a_reorder_renumbers() -> None:
    stored = [_stored(1, "A"), _stored(2, "B"), _stored(3, "C")]

    plan = _plan(stored, _file(("C", "Groceries"), ("A", "Groceries"), ("B", "Groceries")))

    assert [p.priority for p in plan.rules] == [100, 200, 300]
    assert _order_after(stored, plan) == ["C", "A", "B"]


def test_a_file_of_only_new_rules_numbers_them_from_one_step() -> None:
    plan = _plan([], _file(("A", "Groceries"), ("B", "Groceries")))

    assert [p.priority for p in plan.rules] == [100, 200]


@pytest.mark.parametrize(
    "order",
    ["ABCD", "DCBA", "BDAC", "AXBCD", "XABCDY", "ACXBD", "CAXB", "XYZ", "AD", "DXA"],
)
def test_the_resulting_order_always_equals_file_order(order: str) -> None:
    stored = [_stored(1, "A", priority=100), _stored(2, "B", priority=100), _stored(3, "C", priority=250), _stored(4, "D", priority=250)]

    plan = _plan(stored, _file(*((p, "Groceries") for p in order)))

    assert _order_after(stored, plan) == list(order)
