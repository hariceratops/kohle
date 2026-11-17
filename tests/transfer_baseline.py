"""The transfer-rules no-regression oracle's ledger and command script (issues 126, 136). Design §18.6.

`run_script` drives a two-account ledger whose transfers are routed through an
`account = "Transfers"` clearing rule, in both import orders. The text it
returns was captured from the pre-feature code into
`fixtures/transfer_baseline.txt` before issue 126 changed any behaviour. Do not
edit the script without recapturing from pre-feature code, which no longer
exists. It deliberately omits `reclassify` onto an own account, which the spec
changes (design §17.9).
"""

import os
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy.orm import sessionmaker

from kohle.app.cli.cli import cli
from tests.pre_feature_baseline import FIXTURES, TODAY

BASELINE = FIXTURES / "transfer_baseline.txt"

RULES = (
    '[[rule]]\naccount = "Transfers"\n[rule.when]\niban = "DE44500105175407324931"\n\n'
    '[[rule]]\naccount = "Transfers"\n[rule.when]\niban = "DE89370400440532013000"\n\n'
    '[[rule]]\naccount = "Groceries"\n[rule.when]\ndescription = "aldi"\n'
)

SCRIPT: list[list[str]] = [
    ["add-unit", "EUR", "Euro", "--kind", "currency"],
    ["add-account", "Checking", "--type", "asset", "--iban", "DE89370400440532013000"],
    ["add-account", "Savings", "--type", "asset", "--iban", "DE44500105175407324931"],
    ["add-account", "Checking2", "--type", "asset"],
    ["add-account", "Savings2", "--type", "asset"],
    ["add-account", "People", "--type", "asset"],
    ["add-account", "Transfers", "--type", "asset"],
    ["add-account", "Groceries", "--type", "expense"],
    ["add-account", "Rent", "--type", "expense"],
    # Checking first, no rules yet: both rows fall through, classify-rules moves them.
    ["import-statement", "kohle-deutsche-bank", "Checking", "@CHECKING@"],
    ["import-statement", "kohle-deutsche-bank", "Savings", "@SAVINGS@"],
    ["list-unclassified"],
    ["apply-rules", "@RULES@", "--yes"],
    ["classify-rules"],
    ["classify-rules", "--yes"],
    ["list-unclassified"],
    # Savings first, rules in place: both rows are classified at import.
    ["import-statement", "kohle-deutsche-bank", "Savings2", "@SAVINGS@"],
    ["import-statement", "kohle-deutsche-bank", "Checking2", "@CHECKING@"],
    ["import-statement", "kohle-deutsche-bank", "Checking2", "@CHECKING@"],
    ["list-unclassified"],
    ["reclassify", "11", "Rent"],
    ["list-unclassified"],
    ["show-rules"],
    ["list-accounts"],
    ["balance", "Checking"],
    ["balance", "Savings"],
    ["balance", "Checking2"],
    ["balance", "Savings2"],
    ["balance", "Transfers"],
    ["balance", "Groceries"],
    ["balance", "Rent"],
    ["balance", "Unclassified Expense"],
    ["balance", "Unclassified Income"],
    ["entries-in-period", "Transfers", "2026-01-01", "2026-12-31"],
    ["net-worth"],
    ["budget", "--from", "2026-01-01"],
    ["list-operations"],
]


def run_script(session_factory: sessionmaker) -> str:
    """Run `SCRIPT` and return one block per command: the command line, the
    exit code, and the output."""
    blocks: list[str] = []
    with pytest.MonkeyPatch.context() as mp, tempfile.TemporaryDirectory() as tmp:
        files = {
            "@CHECKING@": str(FIXTURES / "transfer_checking.csv"),
            "@SAVINGS@": str(FIXTURES / "transfer_savings.csv"),
            "@RULES@": str(Path(tmp) / "rules.toml"),
        }
        Path(files["@RULES@"]).write_text(RULES)
        mp.setenv("XDG_CONFIG_HOME", str(Path(tmp) / "config"))
        mp.setenv("XDG_DATA_HOME", str(Path(tmp) / "data"))
        mp.setenv("KOHLE_DB", os.path.join(tmp, "unused.db"))
        mp.setattr("kohle.app.cli.cli.date", _pinned_date())

        runner = CliRunner()
        for args in SCRIPT:
            args = [files.get(a, a) for a in args]
            result = runner.invoke(cli, args, obj=session_factory)
            shown = " ".join(a if not a.startswith("/") else Path(a).name for a in args)
            blocks.append(f"$ {shown}\n[exit {result.exit_code}]\n{result.output}")
    return "\n".join(blocks)


def _pinned_date():
    from datetime import date

    class PinnedDate(date):
        @classmethod
        def today(cls) -> "PinnedDate":
            return cls(TODAY.year, TODAY.month, TODAY.day)

    return PinnedDate
