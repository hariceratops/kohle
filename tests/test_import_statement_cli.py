"""import-statement CLI (issue 027)."""

import pytest


def test_import_statement_four_positional_form() -> None:
    # TODO: monkeypatch kohle.app.cli.cli.load_plugins to the synthetic plugin and run the four-positional form; the three-positional Deutsche Bank form still parses; two instrument accounts is a usage error; a plugin error exits non-zero with its message.
    pytest.skip("scaffold")
