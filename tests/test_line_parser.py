"""Layer 1 — pure unit tests, no fixture.

The `record-split` --line parser (issue 006). Parsing
ACCOUNT:QUANTITY:UNIT:PRICE:SIDE is the one place the CLI is allowed to
reject input, because it cannot construct a use-case call from a malformed
value. See dev/design/cli-record-and-balances.md.
"""


def test_placeholder() -> None:
    # TODO: a well-formed --line value parses to the expected fields
    # TODO: wrong field count names the offending value, does not raise
    # TODO: SIDE outside {debit, credit} is rejected
    # TODO: non-numeric QUANTITY is rejected
    # TODO: non-numeric PRICE is rejected
    # TODO: empty ACCOUNT is rejected
    # TODO: quantity and price parse to Decimal, never float
    assert True
