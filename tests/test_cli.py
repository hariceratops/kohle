"""Layer 4 — CLI tests through Click's CliRunner.

BLOCKED until issue 009 lands. Every command currently constructs
`session_local()` inline, which is bound to the real kohle.db, so invoking one
from a test would write to the user's actual ledger. Once the session factory
comes from Click's context object, these run against the `session_factory`
fixture in conftest — which already exists and is used by nothing.

This layer covers what the layers below cannot: that a domain error reaches
the user as a message rather than a traceback, and that output renders the
way the acceptance criteria describe.
"""

from sqlalchemy.orm import sessionmaker


def test_placeholder(session_factory: sessionmaker) -> None:
    # TODO: the fixture-injected factory is used, and the real kohle.db is
    #       untouched by a test run — assert this first, it is the whole
    #       reason this layer can exist
    # TODO: record posts an entry and reports success
    # TODO: an unknown account prints a readable message, not a traceback
    # TODO: a non-zero exit code accompanies a failed command
    # TODO: record-split with a malformed --line names the offending value
    # TODO: balance renders one row per unit through tabulate
    # TODO: list-accounts renders nesting with |- connectors, since tabulate
    #       strips leading whitespace (issue 007)
    # TODO: the operations command lists the audit trail (issue 008)
    assert True
