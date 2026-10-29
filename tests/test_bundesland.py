"""Layer 1 — Bundesland history in kohle/use_cases/bundesland.py (issues 069-070). Design §18.3."""

from datetime import date

import pytest
from sqlalchemy import func

from kohle.domain.domain_errors import InvalidState, NoStartState
from kohle.domain.models import START, Operation, OperationGroup, StateEntry
from kohle.use_cases.bundesland import STATES, ListStates, state_lookup, validate_state


def _entries(*pairs: tuple[date, str]) -> list[StateEntry]:
    return [StateEntry(effective_from=on, state=state) for on, state in pairs]


def test_state_lookup_start_move_and_future() -> None:
    lookup = state_lookup(_entries((START, "BY"), (date(2026, 1, 1), "NI"))).unwrap()

    assert lookup(date(2025, 12, 31)) == "BY"
    assert lookup(date(2026, 1, 1)) == "NI"
    assert lookup(date(2040, 6, 1)) == "NI"


def test_state_lookup_covers_a_start_only_history() -> None:
    lookup = state_lookup(_entries((START, "BY"))).unwrap()

    assert lookup(date(1990, 1, 1)) == "BY"


def test_state_lookup_refuses_an_empty_history() -> None:
    assert isinstance(state_lookup([]).unwrap_err(), NoStartState)


def test_state_lookup_refuses_a_dated_only_history() -> None:
    err = state_lookup(_entries((date(2026, 1, 1), "NI"))).unwrap_err()

    assert isinstance(err, NoStartState)


@pytest.mark.parametrize("code", STATES)
def test_validate_state_accepts_every_bundesland_code(code: str) -> None:
    assert validate_state(code).unwrap() == code


@pytest.mark.parametrize("bad", ["XX", "by", "", 1, None, ["BY"], "Augsburg"])
def test_validate_state_rejects_other_codes_case_and_types(bad: object) -> None:
    err = validate_state(bad).unwrap_err()

    assert isinstance(err, InvalidState)
    assert str(err).endswith(f"expected one of {', '.join(STATES)}")


def test_list_states_is_oldest_first_and_leaves_no_operation_group(session_factory) -> None:
    with session_factory() as s:
        s.add_all(_entries((date(2026, 1, 1), "NI"), (START, "BY")))
        s.commit()

    listed = ListStates(session_factory()).execute().unwrap()

    assert [(e.effective_from, e.state) for e in listed] == [(START, "BY"), (date(2026, 1, 1), "NI")]
    with session_factory() as s:
        assert s.query(func.count(OperationGroup.id)).scalar() == 0
        assert s.query(func.count(Operation.id)).scalar() == 0
