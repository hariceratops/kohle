"""The dates `net-worth-history` samples: roles, the stored rule list, and
the sample dates it yields (design §7.2)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    EmptySamplingRules,
    InvalidRole,
    SamplingRulesError,
)
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.sampling_services import current_rule_list_service
from kohle.use_cases.recurrence import (
    Recurrence,
    occurrences,
    parse_recurrence,
    render_recurrence,
)

# Written out because `holidays.Germany.subdivisions` also lists "Augsburg",
# a city, which is not a Bundesland.
STATES = (
    "BB", "BE", "BW", "BY", "HB", "HE", "HH", "MV",
    "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH",
)


class Role(Enum):
    mid_month = "mid-month"
    salary = "salary"


@dataclass(frozen=True, slots=True)
class SamplingRule:
    role: Role
    recurrence: Recurrence


@dataclass(frozen=True, slots=True)
class Sample:
    on: date
    roles: tuple[Role, ...]  # Role order; () only for the --to row that no rule reached


def parse_sampling_rules(text: str) -> Result[list[SamplingRule], SamplingRulesError]:
    rules: list[SamplingRule] = []
    for item in text.split(";"):
        if not item.strip():
            continue
        role_text, colon, rule_text = item.partition(":")
        if not colon:
            return Result.err(InvalidRole(item.strip(), None))
        try:
            role = Role(role_text.strip())
        except ValueError:
            return Result.err(InvalidRole(item.strip(), role_text.strip()))
        recurrence = parse_recurrence(rule_text)
        if recurrence.is_err:
            return Result.err(recurrence.unwrap_err())
        rules.append(SamplingRule(role, recurrence.unwrap()))
    if not rules:
        return Result.err(EmptySamplingRules())
    return Result.ok(rules)


def render_sampling_rules(rules: Sequence[SamplingRule]) -> str:
    return "; ".join(f"{r.role.value}: {render_recurrence(r.recurrence)}" for r in rules)


def sample_dates(
    rules: Sequence[SamplingRule], state_on: Callable[[date], str], start: date, end: date
) -> list[Sample]:
    """Every date a rule lands on in [start, end], one Sample per date with
    every role that reached it, ascending; then `end` with no role unless it
    is already the last date. No price access: a backfill can call this to
    learn which dates need closes."""
    roles_by_date: dict[date, set[Role]] = {}
    for rule in rules:
        for day in occurrences(rule.recurrence, start, end, state_on):
            roles_by_date.setdefault(day, set()).add(rule.role)
    samples = [
        Sample(day, tuple(r for r in Role if r in roles_by_date[day])) for day in sorted(roles_by_date)
    ]
    if not samples or samples[-1].on != end:
        samples.append(Sample(end, ()))
    return samples


def current_sampling_rules(ctx: DbTransactionContext) -> Result[list[SamplingRule], SamplingRulesError]:
    stored = current_rule_list_service(ctx)
    if stored.is_err:
        return Result.err(stored.unwrap_err())
    return parse_sampling_rules(stored.unwrap().rules)
