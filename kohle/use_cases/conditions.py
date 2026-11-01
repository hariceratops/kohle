"""The classification-rule condition language: parse, render, compile.

Pure: no session, no I/O. A rule's `when` is stored as canonical TOML text and
read back through `parse_stored_when` (design §2, §3).
"""

import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from kohle.core.result import Result
from kohle.domain.domain_errors import MalformedRuleFile
from kohle.services.journal_services import Counterparty

# Matching is case-insensitive because bank exports are inconsistently cased —
# REWE SAGT DANKE and Rewe Markt GmbH are the same payee and a user writing
# 'rewe' means both. (?-i:...) restores case sensitivity within a pattern.
PATTERN_FLAGS = re.IGNORECASE


@dataclass(frozen=True, slots=True)
class When:
    """One TOML condition table: every key present must hold.

    One field per key rather than a node hierarchy, because a TOML table can
    hold each key once. Equality is then content identity, independent of key
    order in the file."""

    description: str | None = None
    counterparty: str | None = None
    iban: str | None = None  # normalised: no whitespace, upper case
    any_field: str | None = None


def normalise_iban(iban: str) -> str:
    return "".join(iban.split()).upper()


Predicate = Callable[[str, Counterparty], bool]


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


_CONDITION_KEYS = ("description", "counterparty", "iban", "any_field")


def parse_when(value: object, key: str = "when") -> Result[When, MalformedRuleFile]:
    if not isinstance(value, dict) or not value:
        return Result.err(MalformedRuleFile(None, key, "must be a table with at least one condition"))
    for name in value:
        if name not in _CONDITION_KEYS:
            return Result.err(MalformedRuleFile(None, f"{key}.{name}", "is not a known condition"))
    fields: dict[str, str] = {}
    for name in _CONDITION_KEYS:
        if name not in value:
            continue
        checked = (_check_iban if name == "iban" else _check_pattern)(value[name], f"{key}.{name}")
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


def _render_parts(when: When) -> list[str]:
    parts = []
    for name in _CONDITION_KEYS:
        value = getattr(when, name)
        if value is not None:
            parts.append(f"{name} = {toml_string(value)}")
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
        tests.append(lambda description, counterparty: description_pattern.search(description) is not None)
    if when.counterparty is not None:
        name_pattern = re.compile(when.counterparty, PATTERN_FLAGS)
        tests.append(
            lambda description, counterparty: counterparty.name is not None
            and name_pattern.search(counterparty.name) is not None
        )
    if when.iban is not None:
        wanted = when.iban
        tests.append(
            lambda description, counterparty: counterparty.iban is not None
            and normalise_iban(counterparty.iban) == wanted
        )
    if when.any_field is not None:
        pattern = re.compile(when.any_field, PATTERN_FLAGS)

        def any_field(description: str, counterparty: Counterparty) -> bool:
            # Matched per field so an anchored pattern means "this exact IBAN"
            # rather than "start and end of a blob".
            fields = (description, counterparty.name, counterparty.iban)
            return any(pattern.search(f) for f in fields if f is not None)

        tests.append(any_field)
    return lambda description, counterparty: all(test(description, counterparty) for test in tests)
