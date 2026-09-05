"""Layer 3 — use-case tests against the `session` fixture.

The entry-posting use case behind `record` (issues 001, 004).

The point of these is that the CLI adds no validation: balance-by-value and
leaf-only posting are enforced once, in the use case, so a TUI or any other
frontend gets them free. Assertions are on `Result` and on domain error
types, matching the existing use-case tests.
"""

from sqlalchemy.orm import Session


def test_placeholder(session: Session) -> None:
    # Base currency, issue 001
    # TODO: a two-line base-currency entry posts and balances
    # TODO: --from is credited, --to is debited, both at unit_price 1
    # TODO: the reference is system-generated and differs between two
    #       otherwise identical entries
    # TODO: an unknown account name returns AccountNotFoundError
    # TODO: posting to an account with children returns
    #       PostingToNonLeafAccount
    # TODO: EUR is created on first use rather than failing on a fresh install
    assert True


def test_cross_unit_placeholder(session: Session) -> None:
    # Cross-unit, issue 004 — the direction is the whole point
    # TODO: a purchase (units arrive via the debit side) posts correctly
    # TODO: a sale (units leave via the credit side) posts correctly and is
    #       reachable without record-split
    # TODO: both balance by value: the base-currency side is quantity x price
    # TODO: naming a base-currency unit on either side is a domain error,
    #       with or without a price
    # TODO: a sale of a unit never bought is posted, not rejected — the
    #       ledger records what happened
    assert True
