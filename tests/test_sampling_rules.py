"""Layer 1 — rule-list parsing and merging in kohle/use_cases/sampling.py (issues 064-068). Design §18.3."""

from datetime import date

import pytest

from kohle.domain.domain_errors import EmptySamplingRules, InvalidRecurrence, InvalidRole
from kohle.use_cases.recurrence import Day, LastWorkday
from kohle.use_cases.sampling import (
    Role,
    Sample,
    SamplingRule,
    parse_sampling_rules,
    render_sampling_rules,
    sample_dates,
)

DEFAULT = "mid-month: day 15; salary: last workday"


def _by(_: date) -> str:
    return "BY"


def _default():
    return parse_sampling_rules(DEFAULT).unwrap()


def test_the_default_list_parses_and_renders_to_itself() -> None:
    rules = _default()

    assert rules == [SamplingRule(Role.mid_month, Day(15)), SamplingRule(Role.salary, LastWorkday())]
    assert render_sampling_rules(rules) == DEFAULT


@pytest.mark.parametrize("text", ["", ";", " ; ; "])
def test_an_empty_list_is_refused(text: str) -> None:
    assert isinstance(parse_sampling_rules(text).unwrap_err(), EmptySamplingRules)


def test_an_item_without_a_role_is_refused() -> None:
    err = parse_sampling_rules("day 15").unwrap_err()

    assert isinstance(err, InvalidRole)
    assert err.role is None
    assert "has no role" in str(err)


def test_an_unknown_role_is_refused_with_the_roles() -> None:
    err = parse_sampling_rules("pay: day 15").unwrap_err()

    assert isinstance(err, InvalidRole)
    assert err.role == "pay"
    assert "roles: mid-month, salary" in str(err)


def test_a_bad_rule_passes_the_recurrence_error_through() -> None:
    err = parse_sampling_rules("salary: day 40").unwrap_err()

    assert isinstance(err, InvalidRecurrence)
    assert "day N with N from 1 to 31" in str(err)


def test_the_first_bad_item_stops_the_parse() -> None:
    err = parse_sampling_rules("salary: day 40; pay: day 1").unwrap_err()

    assert isinstance(err, InvalidRecurrence)


def test_a_trailing_semicolon_and_extra_whitespace_are_accepted() -> None:
    rules = parse_sampling_rules("mid-month:day 15 ;  salary:last  workday;").unwrap()

    assert render_sampling_rules(rules) == DEFAULT


def test_a_repeated_role_is_kept_as_typed() -> None:
    rules = parse_sampling_rules("salary: last workday; salary: day 25").unwrap()

    assert [r.role for r in rules] == [Role.salary, Role.salary]
    assert render_sampling_rules(rules) == "salary: last workday; salary: day 25"


def test_the_default_list_samples_the_15th_and_the_last_workday_then_the_to_row() -> None:
    samples = sample_dates(_default(), _by, date(2026, 10, 1), date(2026, 10, 31))

    assert samples == [
        Sample(date(2026, 10, 15), (Role.mid_month,)),
        Sample(date(2026, 10, 30), (Role.salary,)),
        Sample(date(2026, 10, 31), ()),
    ]


def test_two_rules_on_one_date_make_one_sample_with_roles_in_enum_order() -> None:
    rules = parse_sampling_rules("salary: day 15; mid-month: day 15").unwrap()

    assert sample_dates(rules, _by, date(2026, 5, 1), date(2026, 5, 15)) == [
        Sample(date(2026, 5, 15), (Role.mid_month, Role.salary)),
    ]


def test_two_salary_rules_on_one_date_give_one_salary_role() -> None:
    rules = parse_sampling_rules("salary: day 15; salary: day 15").unwrap()

    assert sample_dates(rules, _by, date(2026, 5, 1), date(2026, 5, 15)) == [
        Sample(date(2026, 5, 15), (Role.salary,)),
    ]


def test_to_keeps_its_roles_when_it_is_already_a_sample_date() -> None:
    samples = sample_dates(_default(), _by, date(2026, 3, 1), date(2026, 3, 31))

    assert samples[-1] == Sample(date(2026, 3, 31), (Role.salary,))
    assert [s.on for s in samples].count(date(2026, 3, 31)) == 1


def test_a_range_no_rule_reaches_is_just_the_to_row() -> None:
    assert sample_dates(_default(), _by, date(2026, 3, 12), date(2026, 3, 12)) == [Sample(date(2026, 3, 12), ())]


def test_samples_before_start_are_dropped() -> None:
    samples = sample_dates(_default(), _by, date(2026, 3, 16), date(2026, 4, 15))

    assert [s.on for s in samples] == [date(2026, 3, 31), date(2026, 4, 15)]


def test_dec_24_and_31_are_never_last_workday_samples() -> None:
    samples = sample_dates(_default(), _by, date(2020, 1, 1), date(2030, 1, 1))

    assert not {date(2028, 12, 24), date(2028, 12, 31)} & {s.on for s in samples}
    assert date(2028, 12, 29) in {s.on for s in samples}
