"""Layer 3 — use-case tests against the `session_factory` fixture.

Classification inside the import loop (issues 013, 015).

Four of these are regression guards rather than feature tests: the code they
cover is correct in a way that is easy to silently break later, and
dev/design/expense-classification.md names each one as a trap.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 013")
def test_counterparty_through_import() -> None:
    # TODO(013) — one test per site:
    #   - ImportStatement stores counterparty_name and counterparty_iban
    #     instead of validating iban and discarding it
    #   - entries made through record/record-split have both as None; no
    #     placeholder value is invented
    #   - a plugin omitting the column entirely fails with
    #     DataframeMissingColumn before any row is touched, because a silently
    #     missing counterparty is what makes a rule quietly stop matching
    #
    # TODO(013) REGRESSION — a statement whose counterparty column is empty on
    #   EVERY row imports successfully. read_csv types an all-empty text column
    #   as float64, so the current iban check already rejects such a statement
    #   (§3.3). This is the one test that would have caught that latent bug.
    #
    # TODO(013) REGRESSION — the reference hash is unchanged: import a
    #   statement, add counterparty data, re-import, assert zero new entries.
    #   The hash is what makes re-imports idempotent (§3.6).
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 015")
def test_classification_in_the_import_loop() -> None:
    # TODO(015) — one test per site:
    #   - a row matching a rule posts to that rule's target account
    #   - a row matching nothing posts to the unclassified bucket exactly as
    #     before; import with an empty rule set is unchanged behaviour
    #   - a classification row is written on both paths
    #   - posting still routes through post_entry: balance-by-value and
    #     leaf-only are not reimplemented here
    #
    # TODO(015) REGRESSION — one import produces exactly ONE OperationGroup,
    #   holding every entry and every classification. Extends
    #   test_write_creates_exactly_one_group_holding_its_operations. This is
    #   the guard against someone making the classifier a UnitOfWork, which
    #   would commit and close the session on the first row and half-commit
    #   the statement (§5.2).
    #
    # TODO(015) REGRESSION — a row failing mid-import leaves no entries, no
    #   classifications and no group. Atomicity asserted, not assumed.
    raise NotImplementedError
