"""Bundesland codes and the effective-dated history (design §7.3)."""

from bisect import bisect_right
from collections.abc import Callable, Sequence
from datetime import date

from kohle.core.result import Result
from kohle.domain.domain_errors import InvalidState, NoStartState, StateError
from kohle.domain.models import START, StateEntry
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.state_services import (
    list_state_entries_service,
    put_state_entry_service,
)

# Written out because `holidays.Germany.subdivisions` also lists "Augsburg",
# a city, which is not a Bundesland.
STATES = (
    "BB", "BE", "BW", "BY", "HB", "HE", "HH", "MV",
    "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH",
)


def validate_state(value: object) -> Result[str, InvalidState]:
    if isinstance(value, str) and value in STATES:
        return Result.ok(value)
    return Result.err(InvalidState(value, STATES))


def state_lookup(entries: Sequence[StateEntry]) -> Result[Callable[[date], str], NoStartState]:
    """`entries` oldest first, as list_state_entries_service returns them.
    Err unless the first entry is START, so the lookup is total."""
    if not entries or entries[0].effective_from != START:
        return Result.err(NoStartState())
    froms = [e.effective_from for e in entries]
    return Result.ok(lambda day: entries[bisect_right(froms, day) - 1].state)


class MoveState(UnitOfWork[StateEntry, StateError]):
    def execute(self, effective_from: date, state: object) -> Result[StateEntry, StateError]:
        valid = validate_state(state)
        if valid.is_err:
            return Result.err(valid.unwrap_err())
        code = valid.unwrap()

        def use_case(ctx: DbTransactionContext) -> Result[StateEntry, StateError]:
            return put_state_entry_service(ctx, effective_from, code)

        return self._run(use_case)


class ListStates(UnitOfWork[list[StateEntry], StateError]):
    def execute(self) -> Result[list[StateEntry], StateError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[StateEntry], StateError]:
            return list_state_entries_service(ctx)

        return self._run(use_case)
