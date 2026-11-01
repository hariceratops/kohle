"""Layer 1 — the condition language: parse, render, evaluate (design §17.1)."""

import tomllib
from decimal import Decimal

import pytest

from kohle.services.journal_services import Counterparty
from kohle.use_cases.conditions import (
    When,
    compile_when,
    parse_stored_when,
    parse_when,
    render_when_inline,
    render_when_lines,
    toml_string,
)

NONE = Counterparty(None, None)


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

    assert holds("x", Counterparty(None, "DE89"))
    assert not holds("x", Counterparty("DE89 Landlord", None))
    assert compile_when(When(any_field="rewe"))("REWE SAGT DANKE", NONE)
    assert not compile_when(When(any_field="rewe"))("ALDI", NONE)


@pytest.mark.skip(reason="TODO: 085 toml_decimal round-trips through tomllib")
def test_placeholder_quoting() -> None:
    raise NotImplementedError


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


@pytest.mark.skip(reason="TODO: 086 AND/OR stop once decided")
def test_placeholder_short_circuit() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason="TODO: 086 rewe, edeka without pfand, edeka with pfand")
def test_placeholder_groceries_example() -> None:
    raise NotImplementedError
