"""The classification-rule condition language: parse, render, compile.

Pure: no session, no I/O. A rule's `when` is stored as canonical TOML text and
read back through `parse_stored_when` (design §2, §3).
"""

import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from kohle.core.result import Result
from kohle.domain.domain_errors import MalformedRuleFile
from kohle.services.journal_services import Counterparty

# Matching is case-insensitive because bank exports are inconsistently cased —
# REWE SAGT DANKE and Rewe Markt GmbH are the same payee and a user writing
# 'rewe' means both. (?-i:...) restores case sensitivity within a pattern.
PATTERN_FLAGS = re.IGNORECASE


class Direction(Enum):
    incoming = "in"
    outgoing = "out"


@dataclass(frozen=True, slots=True)
class AmountRange:
    """Bounds on the absolute amount, both inclusive; at least one is set."""

    low: Decimal | None
    high: Decimal | None


@dataclass(frozen=True, slots=True)
class When:
    """One TOML condition table: every key present must hold.

    One field per key rather than a node hierarchy, because a TOML table can
    hold each key once. Equality is then content identity, independent of key
    order in the file."""

    description: str | None = None
    counterparty: str | None = None
    iban: str | None = None  # normalised: no whitespace, upper case
    amount: AmountRange | None = None
    direction: Direction | None = None
    any_field: str | None = None


def normalise_iban(iban: str) -> str:
    return "".join(iban.split()).upper()


Predicate = Callable[[str, Counterparty, Decimal], bool]


def _check_pattern(value: object, key: str) -> Result[str, MalformedRuleFile]:
    if not isinstance(value, str):
        return Result.err(MalformedRuleFile(None, key, "must be a string"))
    if not value.strip():
        return Result.err(MalformedRuleFile(None, key, "must not be empty"))
    try:
        re.compile(value, PATTERN_FLAGS)
    except re.error as err:
        return Result.err(MalformedRuleFile(None, key, f"is not a valid pattern: {err}"))
    return Result.ok(value)


def _check_iban(value: object, key: str) -> Result[str, MalformedRuleFile]:
    if not isinstance(value, str):
        return Result.err(MalformedRuleFile(None, key, "must be a string"))
    normalised = normalise_iban(value)
    if not re.fullmatch(r"[A-Z0-9]+", normalised):
        return Result.err(
            MalformedRuleFile(
                None, key, "must be an IBAN (letters and digits); use any_field or counterparty for a pattern"
            )
        )
    return Result.ok(normalised)


def _check_bound(value: object, key: str) -> Result[Decimal, MalformedRuleFile]:
    # bool is an int, so it has to be refused before the int branch.
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return Result.err(MalformedRuleFile(None, key, "must be a number"))
    bound = Decimal(value)
    if not bound.is_finite():
        return Result.err(MalformedRuleFile(None, key, "must be a finite number"))
    if bound < 0:
        return Result.err(
            MalformedRuleFile(
                None, key, "must not be negative; the range is on the absolute amount, use direction for the sign"
            )
        )
    return Result.ok(bound)


def _check_amount(value: object, key: str) -> Result[AmountRange, MalformedRuleFile]:
    if not isinstance(value, dict) or not value:
        return Result.err(MalformedRuleFile(None, key, "must be a table with min, max or both"))
    for name in value:
        if name not in ("min", "max"):
            return Result.err(MalformedRuleFile(None, f"{key}.{name}", "is not min or max"))
    bounds: dict[str, Decimal | None] = {"min": None, "max": None}
    for name in bounds:
        if name in value:
            checked = _check_bound(value[name], f"{key}.{name}")
            if checked.is_err:
                return Result.err(checked.unwrap_err())
            bounds[name] = checked.unwrap()
    low, high = bounds["min"], bounds["max"]
    if low is not None and high is not None and low > high:
        return Result.err(MalformedRuleFile(None, key, f"min {toml_decimal(low)} is above max {toml_decimal(high)}"))
    return Result.ok(AmountRange(low, high))


def _check_direction(value: object, key: str) -> Result[Direction, MalformedRuleFile]:
    if value == "in":
        return Result.ok(Direction.incoming)
    if value == "out":
        return Result.ok(Direction.outgoing)
    return Result.err(MalformedRuleFile(None, key, 'must be "in" or "out"'))


_CONDITION_KEYS = ("description", "counterparty", "iban", "amount", "direction", "any_field")
_CHECKS = {"iban": _check_iban, "amount": _check_amount, "direction": _check_direction}


def parse_when(value: object, key: str = "when") -> Result[When, MalformedRuleFile]:
    if not isinstance(value, dict) or not value:
        return Result.err(MalformedRuleFile(None, key, "must be a table with at least one condition"))
    for name in value:
        if name not in _CONDITION_KEYS:
            return Result.err(MalformedRuleFile(None, f"{key}.{name}", "is not a known condition"))
    fields: dict[str, object] = {}
    for name in _CONDITION_KEYS:
        if name not in value:
            continue
        checked = _CHECKS.get(name, _check_pattern)(value[name], f"{key}.{name}")
        if checked.is_err:
            return Result.err(checked.unwrap_err())
        fields[name] = checked.unwrap()
    return Result.ok(When(**fields))


def parse_stored_when(text: str) -> Result[When, MalformedRuleFile]:
    try:
        data = tomllib.loads("when = " + text, parse_float=Decimal)
    except tomllib.TOMLDecodeError as err:
        return Result.err(MalformedRuleFile(None, None, f"not valid TOML: {err}"))
    return parse_when(data["when"])


def toml_string(s: str) -> str:
    """Basic string when nothing needs escaping, else a literal string so a
    regex keeps its single backslashes, else a fully escaped basic string."""
    needs_escape = any((ord(c) < 0x20 and c != "\t") or ord(c) == 0x7F for c in s)
    if not needs_escape and '"' not in s and "\\" not in s:
        return f'"{s}"'
    if not needs_escape and "'" not in s:
        return f"'{s}'"
    escapes = {"\\": "\\\\", '"': '\\"', "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}
    out = []
    for c in s:
        if c in escapes:
            out.append(escapes[c])
        elif ord(c) < 0x20 or ord(c) == 0x7F:
            out.append(f"\\u{ord(c):04X}")
        else:
            out.append(c)
    return '"' + "".join(out) + '"'


def toml_decimal(d: Decimal) -> str:
    # + 0 turns -0 into 0; normalize() drops trailing zeros, and the "f" format
    # keeps an exponent out of the literal.
    return format((d + 0).normalize(), "f")


def _render_value(value: str | AmountRange | Direction) -> str:
    match value:
        case AmountRange():
            bounds = (("min", value.low), ("max", value.high))
            return "{ " + ", ".join(f"{k} = {toml_decimal(b)}" for k, b in bounds if b is not None) + " }"
        case Direction():
            return toml_string(value.value)
        case _:
            return toml_string(value)


def _render_parts(when: When) -> list[str]:
    parts = []
    for name in _CONDITION_KEYS:
        value = getattr(when, name)
        if value is not None:
            parts.append(f"{name} = {_render_value(value)}")
    return parts


def render_when_inline(when: When) -> str:
    return "{ " + ", ".join(_render_parts(when)) + " }"


def render_when_lines(when: When) -> list[str]:
    """The body under `[rule.when]`: one `key = value` line per key."""
    return _render_parts(when)


def compile_when(when: When) -> Predicate:
    tests: list[Predicate] = []
    if when.description is not None:
        description_pattern = re.compile(when.description, PATTERN_FLAGS)
        tests.append(lambda description, counterparty, amount: description_pattern.search(description) is not None)
    if when.counterparty is not None:
        name_pattern = re.compile(when.counterparty, PATTERN_FLAGS)
        tests.append(
            lambda description, counterparty, amount: counterparty.name is not None
            and name_pattern.search(counterparty.name) is not None
        )
    if when.iban is not None:
        wanted = when.iban
        tests.append(
            lambda description, counterparty, amount: counterparty.iban is not None
            and normalise_iban(counterparty.iban) == wanted
        )
    if when.amount is not None:
        low, high = when.amount.low, when.amount.high
        tests.append(
            lambda description, counterparty, amount: (low is None or low <= abs(amount))
            and (high is None or abs(amount) <= high)
        )
    if when.direction is not None:
        incoming = when.direction is Direction.incoming
        # A zero line moves no money, so it is neither in nor out.
        tests.append(lambda description, counterparty, amount: amount > 0 if incoming else amount < 0)
    if when.any_field is not None:
        pattern = re.compile(when.any_field, PATTERN_FLAGS)

        def any_field(description: str, counterparty: Counterparty, amount: Decimal) -> bool:
            # Matched per field so an anchored pattern means "this exact IBAN"
            # rather than "start and end of a blob".
            fields = (description, counterparty.name, counterparty.iban)
            return any(pattern.search(f) for f in fields if f is not None)

        tests.append(any_field)
    return lambda description, counterparty, amount: all(test(description, counterparty, amount) for test in tests)
