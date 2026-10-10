"""Layer 1 — pure unit tests, no fixture.

The debt-simplification netting function `settle` (issue 023). Every decision
in dev/design/expense-splitting.md §8.1 — the greedy max-payer/max-receiver
pairing, the tie-break, the participant set including the user as `None` —
lives in this one pure function and none of it touches a session.
"""

from decimal import Decimal

from kohle.use_cases.splitting import settle


def test_settle_acceptance_case_one_intermediary_one_transfer() -> None:
    # Alice +50 (owes), Bob -50 (owed), you 0 — one transfer, not two or
    # three (spec's acceptance case).
    transfers = settle({"Alice": Decimal(50), "Bob": Decimal(-50), None: Decimal(0)})
    assert transfers == [("Alice", "Bob", Decimal(50))]


def test_settle_star_case_nothing_cancels_through_a_third_party() -> None:
    # Two people both owe you: nothing to net through a third party.
    transfers = settle({"Alice": Decimal(30), "Bob": Decimal(20), None: Decimal(-50)})
    assert transfers == [
        ("Alice", None, Decimal(30)),
        ("Bob", None, Decimal(20)),
    ]


def test_settle_chain_of_three_nets_to_two_transfers() -> None:
    transfers = settle({"Alice": Decimal(50), "Bob": Decimal(-30), "Carol": Decimal(-20)})
    assert transfers == [
        ("Alice", "Bob", Decimal(30)),
        ("Alice", "Carol", Decimal(20)),
    ]


def test_settle_ties_resolve_identically_across_repeated_runs() -> None:
    positions: dict[str | None, Decimal] = {"Bob": Decimal(50), "Alice": Decimal(-25), "Carol": Decimal(-25)}
    first = settle(positions)
    second = settle(dict(positions))
    assert first == second
    # Alice and Carol tie at -25: the (-amount, name or "") key orders the
    # whole participant set once, so the tied pair resolves alphabetically
    # (Carol > Alice) the same way on every run.
    assert first == [
        ("Bob", "Carol", Decimal(25)),
        ("Bob", "Alice", Decimal(25)),
    ]


def test_settle_all_zero_input_returns_no_transfers() -> None:
    assert settle({"Alice": Decimal(0), "Bob": Decimal(0), None: Decimal(0)}) == []


def test_settle_applying_transfers_drives_every_position_to_zero() -> None:
    positions = {"Alice": Decimal(50), "Bob": Decimal(-30), "Carol": Decimal(-20), None: Decimal(0)}
    transfers = settle(dict(positions))

    result = dict(positions)
    for payer, payee, quantity in transfers:
        result[payer] -= quantity
        result[payee] += quantity

    assert all(amount == 0 for amount in result.values())
