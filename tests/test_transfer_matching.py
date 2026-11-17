"""Layer 1 — pure mirror matching, rule file and replay (issues 126-127, 135). Design §18.1."""

import hashlib
from datetime import date, timedelta
from decimal import Decimal

import pytest

from kohle.domain.models import RuleKind
from kohle.services.journal_services import Counterparty
from kohle.use_cases.conditions import When
from kohle.use_cases.rules import (
    CompiledRule,
    FileRule,
    RuleFile,
    StoredRule,
    compile_rules,
    match_rule,
    parse_rule_file,
    plan_rule_changes,
    render_rule_file,
    rule_set_base,
)
from kohle.use_cases.transfers import (
    RowSide,
    TransferSide,
    is_mirror,
    nearest_row,
    nearest_transfer,
)

NOBODY = Counterparty(None, None)
ACCOUNTS = {"Savings": 1, "Groceries": 2}


def _compiled(*kinds_and_accounts: tuple[RuleKind, int]) -> list[CompiledRule]:
    return compile_rules(
        StoredRule(i, i * 100, account_id, "x", When(description="move"), None, kind)
        for i, (kind, account_id) in enumerate(kinds_and_accounts, start=1)
    )


def test_a_transfer_rule_into_the_statement_account_is_skipped_and_the_next_rule_wins() -> None:
    compiled = _compiled((RuleKind.transfer, 1), (RuleKind.category, 2))

    matched = match_rule(compiled, "move", NOBODY, Decimal(-5), statement_account_id=1)

    assert matched is not None and matched.rule_id == 2


def test_a_transfer_rule_matches_a_row_imported_anywhere_else() -> None:
    compiled = _compiled((RuleKind.transfer, 1), (RuleKind.category, 2))

    matched = match_rule(compiled, "move", NOBODY, Decimal(-5), statement_account_id=3)

    assert matched is not None and (matched.rule_id, matched.kind) == (1, RuleKind.transfer)


def test_a_category_rule_aimed_at_the_statement_account_is_not_skipped() -> None:
    compiled = _compiled((RuleKind.category, 1))

    matched = match_rule(compiled, "move", NOBODY, Decimal(-5), statement_account_id=1)

    assert matched is not None and matched.rule_id == 1


def test_the_four_argument_call_never_skips() -> None:
    compiled = _compiled((RuleKind.transfer, 1))

    assert match_rule(compiled, "move", NOBODY, Decimal(-5)) is not None


def _error(text: str) -> str:
    result = parse_rule_file(text)
    assert result.is_err
    return str(result.unwrap_err())


_WHEN = '[rule.when]\ndescription = "x"\n'


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (f'[[rule]]\naccount = "A"\ntransfer = "B"\n{_WHEN}', "rule 1, transfer: cannot be combined with account"),
        (f'[[rule]]\ntransfer = "B"\naccount = "A"\n{_WHEN}', "rule 1, account: cannot be combined with transfer"),
        (f'[[rule]]\ntransfer = ""\n{_WHEN}', "rule 1, transfer: must be a non-empty string"),
        (f'[[rule]]\ntransfer = 3\n{_WHEN}', "rule 1, transfer: must be a non-empty string"),
        (f'[[rule]]\n{_WHEN}', "rule 1, account: is required"),
    ],
)
def test_every_action_key_rejection_names_the_rule_and_the_key(text: str, message: str) -> None:
    assert _error(text) == message


def test_a_transfer_rule_parses_to_a_transfer_kind() -> None:
    rule = parse_rule_file(f'[[rule]]\ntransfer = "Savings"\n{_WHEN}').unwrap().rules[0]

    assert (rule.account, rule.kind) == ("Savings", RuleKind.transfer)


def test_the_same_conditions_and_account_as_a_category_and_a_transfer_are_not_duplicates() -> None:
    text = f'[[rule]]\naccount = "A"\n{_WHEN}[[rule]]\ntransfer = "A"\n{_WHEN}'

    assert parse_rule_file(text).is_ok


def _stored(rule_id: int, kind: RuleKind, account: str = "Savings") -> StoredRule:
    return StoredRule(rule_id, rule_id * 100, ACCOUNTS[account], account, When(description="x"), None, kind)


def test_a_rule_set_round_trips_through_render_and_parse_for_both_kinds() -> None:
    stored = [_stored(1, RuleKind.category), _stored(2, RuleKind.transfer)]

    text = render_rule_file(stored)
    parsed = parse_rule_file(text).unwrap()

    assert [(r.account, r.kind) for r in parsed.rules] == [("Savings", RuleKind.category), ("Savings", RuleKind.transfer)]
    assert 'transfer = "Savings"' in text and 'account = "Savings"' in text
    plan = plan_rule_changes(stored, parsed, ACCOUNTS, rule_set_base(stored))
    assert plan.is_empty


def test_a_category_only_set_renders_without_a_kind_key_and_keeps_its_base() -> None:
    stored = [_stored(1, RuleKind.category, "Groceries")]

    text = render_rule_file(stored)

    assert "transfer" not in text.split("base = ")[1]
    body = '[[rule]]\naccount = "Groceries"\n[rule.when]\ndescription = "x"\n'
    assert text.endswith(body)
    # A base copied from a file rendered before transfers existed must stay valid.
    assert rule_set_base(stored) == hashlib.sha256(body.encode()).hexdigest()[:16]


def test_changing_the_kind_retires_the_rule_and_adds_a_new_one() -> None:
    stored = [_stored(1, RuleKind.category)]
    file = RuleFile(None, (FileRule(1, "Savings", None, When(description="x"), RuleKind.transfer),))

    plan = plan_rule_changes(stored, file, ACCOUNTS, "base")

    assert [r.rule_id for r in plan.retired] == [1]
    assert len(plan.added) == 1 and plan.added[0].rule.kind is RuleKind.transfer


SOURCE_IBAN = "DE44500105175407324931"


def _transfer(day: date, amount: str = "-500.00", entry_id: int = 1, iban: str | None = None) -> TransferSide:
    return TransferSide(entry_id, day, Decimal(amount), 9, iban)


def _row(day: date, amount: str = "500.00", iban: str | None = None) -> RowSide:
    return RowSide(day, Decimal(amount), iban)


APRIL_3 = date(2026, 4, 3)


@pytest.mark.parametrize(
    ("days", "expected"), [(-4, False), (-3, True), (0, True), (3, True), (4, False)]
)
def test_the_window_is_three_calendar_days_either_way_inclusive(days: int, expected: bool) -> None:
    assert is_mirror(_transfer(APRIL_3), _row(APRIL_3 + timedelta(days=days))) is expected


@pytest.mark.parametrize(("amount", "expected"), [("500.00000000", True), ("500", True), ("500.01", False)])
def test_the_amount_must_be_exactly_equal(amount: str, expected: bool) -> None:
    assert is_mirror(_transfer(APRIL_3, "-500.00"), _row(APRIL_3, amount)) is expected


def test_a_row_going_the_same_way_is_not_a_mirror() -> None:
    assert not is_mirror(_transfer(APRIL_3, "-500.00"), _row(APRIL_3, "-500.00"))


def test_an_inbound_transfer_is_mirrored_by_an_outgoing_row() -> None:
    assert is_mirror(_transfer(APRIL_3, "500.00"), _row(APRIL_3, "-500.00"))


@pytest.mark.parametrize(
    ("source", "row", "expected"),
    [
        (SOURCE_IBAN, "de44 5001 0517 5407 3249 31", True),
        (SOURCE_IBAN, "DE02120300000000202051", False),
        (None, "DE02120300000000202051", True),
        (SOURCE_IBAN, None, True),
    ],
)
def test_the_ibans_must_agree_when_both_are_known(source: str | None, row: str | None, expected: bool) -> None:
    assert is_mirror(_transfer(APRIL_3, iban=source), _row(APRIL_3, iban=row)) is expected


def test_the_nearest_transfer_wins() -> None:
    near, far = _transfer(date(2026, 4, 4), entry_id=2), _transfer(date(2026, 4, 1), entry_id=1)

    assert nearest_transfer(_row(date(2026, 4, 3)), [far, near]) is near


def test_equal_distance_goes_to_the_earlier_date_then_the_lower_entry_id() -> None:
    before, after = _transfer(date(2026, 4, 2), entry_id=5), _transfer(date(2026, 4, 4), entry_id=1)
    same_day_low, same_day_high = _transfer(date(2026, 4, 2), entry_id=3), _transfer(date(2026, 4, 2), entry_id=7)

    assert nearest_transfer(_row(date(2026, 4, 3)), [after, before]) is before
    assert nearest_transfer(_row(date(2026, 4, 3)), [same_day_high, same_day_low]) is same_day_low


def test_nothing_within_the_window_gives_none() -> None:
    assert nearest_transfer(_row(date(2026, 4, 20)), [_transfer(APRIL_3)]) is None
    assert nearest_row(_transfer(APRIL_3), [(1, _row(date(2026, 4, 20)))]) is None


def test_the_nearest_row_wins_and_ties_go_to_the_earlier_date_then_the_lower_id() -> None:
    transfer = _transfer(APRIL_3)
    rows = [(4, _row(date(2026, 4, 5))), (3, _row(date(2026, 4, 4))), (2, _row(date(2026, 4, 2))), (1, _row(date(2026, 4, 2)))]

    assert nearest_row(transfer, rows) == 1
    assert nearest_row(transfer, rows[:3]) == 2
    assert nearest_row(transfer, rows[:2]) == 3


@pytest.mark.skip(reason="scaffold")
def test_lots_replay_nets_a_completion_and_its_reversal_to_nothing() -> None:
    # TODO: §18.1 (issue 135): lots.replay with a reversal pair
    ...
