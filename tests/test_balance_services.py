"""Layer 2 — service tests against the `session` fixture.

The balance aggregation query (issues 002, 003).

Eager loading matters here: `UnitOfWork` closes its session before the caller
reads the result, so anything the CLI displays has to be loaded in the
service. This has already bitten once — `query_lines_by_period_service` needs
joinedload on entry and unit for exactly this reason.
"""

from sqlalchemy.orm import Session


def test_placeholder(session: Session) -> None:
    # TODO: quantity is debits minus credits per the is_debit convention
    # TODO: one row per unit held, never combined across units
    # TODO: an account with no lines returns an empty result, not an error
    # TODO: unit is readable after the session closes (eager loading)
    # TODO: a base-currency total appears only when the subtree holds exactly
    #       one unit and that unit is the base currency
    # TODO: rollup aggregates every descendant, not only direct children
    assert True
