"""Layer 1 — pure unit tests, no fixture.

The moving-average cost fold (issue 005). The spec's wording admitted three
readings that diverge; the design chose moving average because it is the only
one where sale price cannot contaminate cost basis. These cases are where the
spec was underspecified, so they are the ones worth pinning down.
See dev/design/cli-record-and-balances.md section 6.4.
"""


def test_placeholder() -> None:
    # TODO: buy 10@100, buy 10@120, sell 5@130, buy 10@200 -> avg cost 146
    #       (the rejected readings give 142 and 140 on the same lines)
    # TODO: a single purchase reports its own price as the average
    # TODO: base-currency holdings report an average cost of 1
    # TODO: selling the entire holding takes quantity to exactly zero
    #       without dividing by zero
    # TODO: quantity going negative (oversold) is reported, not rejected
    # TODO: an account with no lines yields no rows rather than an error
    # TODO: two units in one account stay separate, never combined
    assert True
