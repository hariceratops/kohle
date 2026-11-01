"""Layer 1 — the condition language: parse, render, evaluate (design §17.1)."""

import tomllib
from decimal import Decimal

import pytest

from kohle.services.journal_services import Counterparty
from kohle.use_cases.conditions import (
    AmountRange,
    Direction,
    When,
    compile_when,
    parse_stored_when,
    parse_when,
    render_when_inline,
    render_when_lines,
    toml_decimal,
    toml_string,
)

NONE = Counterparty(None, None)
ONE = Decimal(1)


@pytest.mark.parametrize(
    ("text", "form"),
    [
        ("REWE|ALDI", "basic"),
        (r"\d{4} MIETE", "literal"),
        ("""it's "x" \\d""", "escaped"),
        ("a\tb", "basic"),
        ("a\nb", "escaped"),
        ("a\x7fb", "escaped"),
        ("a\x00b", "escaped"),
        ("m\u00fcller", "basic"),
        ("it's", "basic"),
        ('say "x"', "literal"),
        ("back\\slash", "literal"),
    ],
)
def test_toml_string_round_trips_and_picks_the_expected_form(text: str, form: str) -> None:
    rendered = toml_string(text)

    assert tomllib.loads("x = " + rendered)["x"] == text
    expected_quote = {"basic": '"', "literal": "'", "escaped": '"'}[form]
    assert rendered[0] == expected_quote
    if form == "escaped":
        assert "\\" in rendered


@pytest.mark.parametrize("pattern", ["REWE", r"\d{4} MIETE", """it's "x" \\d""", "tab\there", "m\u00fcller"])
def test_an_any_field_condition_round_trips_through_its_stored_text(pattern: str) -> None:
    when = When(any_field=pattern)

    assert parse_stored_when(render_when_inline(when)).unwrap() == when


def test_render_is_the_compact_inline_form() -> None:
    assert render_when_inline(When(any_field="REWE|ALDI")) == '{ any_field = "REWE|ALDI" }'


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ({}, "when"),
        ("REWE", "when"),
        ({"nope": "x"}, "when.nope"),
        ({"any_field": 3}, "when.any_field"),
        ({"any_field": "  "}, "when.any_field"),
        ({"any_field": "REWE["}, "when.any_field"),
    ],
)
def test_parse_when_rejects_a_bad_any_field_table_naming_the_key(value: object, key: str) -> None:
    err = parse_when(value).unwrap_err()

    assert err.key == key
    assert str(err).startswith(key + ":")


def test_any_field_matches_description_name_or_iban_each_on_its_own() -> None:
    holds = compile_when(When(any_field="^DE89$"))

    assert holds("x", Counterparty(None, "DE89"), ONE)
    assert not holds("x", Counterparty("DE89 Landlord", None), ONE)
    assert compile_when(When(any_field="rewe"))("REWE SAGT DANKE", NONE, ONE)
    assert not compile_when(When(any_field="rewe"))("ALDI", NONE, ONE)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("400", "400"),
        ("400.0", "400"),
        ("4E+2", "400"),
        ("400.50", "400.5"),
        ("400.10", "400.1"),
        ("0.000001", "0.000001"),
        ("-0", "0"),
        ("0.00", "0"),
    ],
)
def test_toml_decimal_is_a_plain_literal_that_parses_back_equal(value: str, text: str) -> None:
    assert toml_decimal(Decimal(value)) == text
    assert tomllib.loads("x = " + text, parse_float=Decimal)["x"] == Decimal(value)


@pytest.mark.parametrize(
    "amount",
    [AmountRange(Decimal(400), Decimal(600)), AmountRange(Decimal("400.1"), None), AmountRange(None, Decimal("0.01"))],
)
@pytest.mark.parametrize("direction", [None, Direction.incoming, Direction.outgoing])
def test_amount_and_direction_round_trip_in_both_forms(amount: AmountRange, direction: Direction | None) -> None:
    when = When(iban="DE89370400440532013000", amount=amount, direction=direction)

    inline = tomllib.loads("when = " + render_when_inline(when), parse_float=Decimal)["when"]
    lines = tomllib.loads("\n".join(render_when_lines(when)), parse_float=Decimal)

    assert parse_when(inline).unwrap() == when
    assert parse_when(lines).unwrap() == when


def test_amount_renders_in_canonical_key_order_with_open_ends_omitted() -> None:
    when = When(direction=Direction.outgoing, amount=AmountRange(Decimal("400.10"), None), iban="DE89")

    assert render_when_inline(when) == '{ iban = "DE89", amount = { min = 400.1 }, direction = "out" }'


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ({"amount": {}}, "when.amount"),
        ({"amount": 5}, "when.amount"),
        ({"amount": {"min": 1, "mid": 2}}, "when.amount.mid"),
        ({"amount": {"min": True}}, "when.amount.min"),
        ({"amount": {"max": "5"}}, "when.amount.max"),
        ({"amount": {"min": Decimal("NaN")}}, "when.amount.min"),
        ({"amount": {"max": Decimal("Infinity")}}, "when.amount.max"),
        ({"amount": {"min": -1}}, "when.amount.min"),
        ({"amount": {"min": 600, "max": 400}}, "when.amount"),
        ({"direction": "sideways"}, "when.direction"),
        ({"direction": 1}, "when.direction"),
    ],
)
def test_parse_when_rejects_a_bad_amount_or_direction_naming_the_key(value: object, key: str) -> None:
    err = parse_when(value).unwrap_err()

    assert err.key == key
    assert str(err).startswith(key + ":")


def test_a_range_with_min_above_max_says_so() -> None:
    err = parse_stored_when("{ amount = { min = 600, max = 400.50 } }").unwrap_err()

    assert str(err) == "when.amount: min 600 is above max 400.5"


def test_int_and_float_bounds_parse_to_the_same_exact_decimal() -> None:
    parsed = parse_stored_when("{ amount = { min = 400, max = 600.10 } }").unwrap()

    assert parsed.amount == AmountRange(Decimal(400), Decimal("600.10"))


def test_amount_range_includes_both_ends_and_either_may_be_open() -> None:
    both = compile_when(When(amount=AmountRange(Decimal(400), Decimal(600))))
    only_min = compile_when(When(amount=AmountRange(Decimal(1500), None)))
    only_max = compile_when(When(amount=AmountRange(None, Decimal(10))))

    assert [both("x", NONE, Decimal(a)) for a in ("399.99", "400", "600", "600.01")] == [False, True, True, False]
    assert both("x", NONE, Decimal(-500))
    assert only_min("x", NONE, Decimal(-2000)) and not only_min("x", NONE, Decimal(-1499))
    assert only_max("x", NONE, Decimal(0)) and not only_max("x", NONE, Decimal("10.01"))


def test_direction_follows_the_sign_and_a_zero_amount_is_neither() -> None:
    incoming = compile_when(When(direction=Direction.incoming))
    outgoing = compile_when(When(direction=Direction.outgoing))

    assert incoming("x", NONE, Decimal(5)) and not incoming("x", NONE, Decimal(-5))
    assert outgoing("x", NONE, Decimal(-5)) and not outgoing("x", NONE, Decimal(5))
    assert not incoming("x", NONE, Decimal(0)) and not outgoing("x", NONE, Decimal(0))


def test_a_line_without_counterparty_name_or_iban_fails_those_conditions_but_not_amount() -> None:
    assert not compile_when(When(counterparty="x"))("x", NONE, ONE)
    assert not compile_when(When(iban="DE89"))("x", NONE, ONE)
    assert compile_when(When(direction=Direction.incoming))("x", NONE, ONE)


@pytest.mark.parametrize("pattern", ["REWE", r"\d{4} MIETE", """it's "x" \\d""", "tab\there", "m\u00fcller"])
def test_a_condition_round_trips_in_both_forms(pattern: str) -> None:
    when = When(any_field=pattern)

    inline = tomllib.loads("when = " + render_when_inline(when), parse_float=Decimal)["when"]
    lines = tomllib.loads("\n".join(render_when_lines(when)), parse_float=Decimal)

    assert parse_when(inline).unwrap() == when
    assert parse_when(lines).unwrap() == when


@pytest.mark.skip(reason="TODO: 084-086 each rejection names its key path")
def test_placeholder_rejections() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason="TODO: 082-086 one test per row of design §3.2, None counterparty, amount bounds, zero amount")
def test_placeholder_semantics() -> None:
    raise NotImplementedError


class _Untouchable:
    """A counterparty whose fields fail the test if evaluation reaches them."""

    @property
    def name(self) -> str:
        raise AssertionError("name was read")

    @property
    def iban(self) -> str:
        raise AssertionError("iban was read")


def test_an_and_stops_at_the_first_failing_key() -> None:
    predicate = compile_when(When(description="x", counterparty="y"))

    assert not predicate("nothing", _Untouchable(), ONE)  # type: ignore[arg-type]


def test_an_or_stops_at_the_first_holding_alternative() -> None:
    predicate = compile_when(When(any_of=(When(description="match"), When(counterparty="y"))))

    assert predicate("a match", _Untouchable(), ONE)  # type: ignore[arg-type]


def test_a_not_over_a_missing_counterparty_holds() -> None:
    assert compile_when(When(not_=When(counterparty="x")))("d", NONE, ONE)
    assert compile_when(When(not_=When(iban="DE89")))("d", NONE, ONE)
    assert not compile_when(When(not_=When(description="d")))("d", NONE, ONE)


GROCERIES = When(any_of=(When(description="rewe"), When(counterparty="edeka", not_=When(description="pfand"))))


def test_the_groceries_example_matches_rewe_and_edeka_without_pfand() -> None:
    groceries = compile_when(GROCERIES)
    edeka = Counterparty("EDEKA Markt", None)

    assert groceries("REWE Markt", NONE, ONE)
    assert groceries("Einkauf", edeka, ONE)
    assert not groceries("Pfand Rueckgabe", edeka, ONE)
    assert not groceries("Einkauf", NONE, ONE)


_NESTED = [
    When(any_of=(When(description="a"), When(iban="DE89"))),
    When(not_=When(counterparty="x")),
    GROCERIES,
    When(
        amount=AmountRange(Decimal("0.5"), None),
        any_of=(When(not_=When(any_of=(When(description="a"), When(not_=When(iban="DE89"))))), When(direction=Direction.incoming)),
        not_=When(any_of=(When(description="b"),)),
    ),
]


@pytest.mark.parametrize("when", _NESTED)
def test_nested_conditions_round_trip_in_all_three_forms(when: When) -> None:
    inline = tomllib.loads("when = " + render_when_inline(when), parse_float=Decimal)["when"]
    lines = tomllib.loads("\n".join(render_when_lines(when)), parse_float=Decimal)

    assert parse_when(inline).unwrap() == when
    assert parse_when(lines).unwrap() == when
    assert parse_stored_when(render_when_inline(when)).unwrap() == when


def test_any_renders_one_alternative_per_line_and_inline_on_one() -> None:
    assert render_when_lines(GROCERIES) == [
        "any = [",
        '  { description = "rewe" },',
        '  { counterparty = "edeka", not = { description = "pfand" } },',
        "]",
    ]
    assert render_when_inline(GROCERIES) == (
        '{ any = [{ description = "rewe" }, { counterparty = "edeka", not = { description = "pfand" } }] }'
    )


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ({"any": []}, "when.any"),
        ({"any": {"description": "x"}}, "when.any"),
        ({"any": [{"description": "x"}, {}]}, "when.any[2]"),
        ({"not": {}}, "when.not"),
        ({"not": "x"}, "when.not"),
        ({"any": [{"description": "x"}, {"not": {"iban": "DE.*"}}]}, "when.any[2].not.iban"),
    ],
)
def test_parse_when_rejects_a_bad_combinator_naming_the_key_path(value: object, key: str) -> None:
    err = parse_when(value).unwrap_err()

    assert err.key == key
