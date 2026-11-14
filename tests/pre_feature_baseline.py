"""The no-regression oracle's ledger and command script (issues 107, 124). Design §14.

`run_script` drives every ledger-opening command against a ledger that holds
only EUR and securities. The text it returns was captured from the pre-feature
code into `fixtures/pre_feature_baseline.txt` before issue 107 changed any
behaviour; issue 124 compares today's output with that file. Do not edit the
script without recapturing from pre-feature code, which no longer exists.
"""

import os
import tempfile
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy.orm import sessionmaker

from kohle.app.cli.cli import cli

FIXTURES = Path(__file__).parent / "fixtures"
BASELINE = FIXTURES / "pre_feature_baseline.txt"
TODAY = date(2026, 6, 15)

PRICE_FILE = "identifier,date,close\nX1,2026-06-12,130.5\nX2,2026-05-01,44.25\n"
RULES = '[[rule]]\naccount = "Groceries"\n[rule.when]\ndescription = "aldi"\n'

SCRIPT: list[list[str]] = [
    ["add-account", "Checking", "--type", "asset", "--iban", "DE89370400440532013000"],
    ["add-account", "Depot", "--type", "asset"],
    ["add-account", "Salary", "--type", "income"],
    ["add-account", "Groceries", "--type", "expense"],
    ["add-account", "Rent", "--type", "expense"],
    ["add-account", "People", "--type", "asset"],
    ["add-account", "Alice", "--type", "asset", "--parent", "People"],
    ["add-account", "Savings", "--type", "asset"],
    ["add-account", "Holiday", "--type", "asset", "--parent", "Savings"],
    ["add-unit", "EUR", "Euro", "--kind", "currency"],
    ["add-unit", "X1", "First thing", "--kind", "security"],
    ["add-unit", "X2", "Second thing", "--kind", "security"],
    ["add-unit", "X3", "Third thing", "--kind", "security"],
    ["add-unit", "DE0005190003", "Broker thing", "--kind", "security"],
    ["list-units"],
    ["list-accounts"],
    ["list-accounts", "Savings"],
    ["list-child-accounts", "Savings"],
    ["move-state", "--from", "start", "BY"],
    ["move-state", "--from", "2026-03-01", "NW"],
    ["list-states"],
    ["list-settings"],
    ["record", "2026-01-02", "salary", "3000", "--from", "Salary", "--to", "Checking"],
    ["record", "2026-01-03", "rent", "900", "--from", "Checking", "--to", "Rent"],
    ["record", "2026-01-10", "buy X1", "10", "--from", "Checking", "--to", "Depot", "--to-unit", "X1", "--to-price", "100"],
    ["record", "2026-02-10", "buy X1 again", "5", "--from", "Checking", "--to", "Depot", "--to-unit", "X1", "--to-price", "120.5"],
    ["record", "2026-02-12", "buy X2", "8", "--from", "Checking", "--to", "Depot", "--to-unit", "X2", "--to-price", "40"],
    ["record", "2026-02-14", "buy X3", "3", "--from", "Checking", "--to", "Depot", "--to-unit", "X3", "--to-price", "7.5"],
    ["record", "2026-04-01", "sell X1", "6", "--from", "Depot", "--to", "Checking", "--from-unit", "X1", "--from-price", "125"],
    [
        "record-split", "2026-03-05", "Groceries and gift",
        "--line", "Checking:80:EUR:1:credit",
        "--line", "Groceries:60:EUR:1:debit",
        "--line", "Holiday:20:EUR:1:debit",
    ],
    ["record", "2026-03-06", "dinner", "45.50", "--from", "Checking", "--to", "Groceries"],
    ["add-group", "Trip"],
    ["set-cap", "--from", "2026-01-01", "Groceries", "100", "day 1"],
    ["set-cap", "--from", "2026-01-01", "Rent", "950", "day 1"],
    ["end-cap", "--from", "2026-05-01", "Rent"],
    ["list-caps"],
    ["list-sampling-rules"],
    ["set-sampling-rules", "mid-month: day 10; salary: last workday"],
    ["list-sampling-rules"],
    ["set-sampling-rules", "mid-month: day 15; salary: last workday"],
    ["list-importer-plugins"],
    ["import-statement", "kohle-deutsche-bank", "Checking", "@BANK@"],
    ["import-statement", "kohle-simple-broker", "Checking", "Depot", "@BROKER@"],
    ["list-unclassified"],
    ["show-rules"],
    ["apply-rules", "@RULES@", "--yes"],
    ["show-rules"],
    ["classify-rules", "--yes"],
    ["list-unclassified"],
    ["reclassify", "10", "Rent"],
    ["split-line", "11", "--mine", "30", "--share", "Alice:12.30", "--group", "Trip"],
    ["who-owes-what"],
    ["who-owes-what", "--by-group"],
    ["settle-up"],
    ["settle-up", "--group", "Trip"],
    ["unsplit-line", "11"],
    ["set-price-source", "X1", "file", "X1"],
    ["set-price-source", "X2", "file", "X2"],
    ["fetch-prices"],
    ["fetch-prices"],
    ["balance", "Checking"],
    ["balance", "Depot"],
    ["balance", "Depot", "--max-age-days", "1"],
    ["balance", "Savings"],
    ["entries-in-period", "Checking", "2026-01-01", "2026-12-31"],
    ["entries-in-period", "Depot", "2026-01-01", "2026-12-31"],
    ["net-worth"],
    ["net-worth", "--max-age-days", "1"],
    ["positions"],
    ["positions", "--max-age-days", "1"],
    ["realised"],
    ["realised", "--year", "2026"],
    ["net-worth-history", "--from", "2026-01-01"],
    ["net-worth-history", "--from", "2026-01-01", "--role", "salary"],
    ["budget", "--from", "2026-01-01"],
    ["list-operations"],
]


def run_script(session_factory: sessionmaker) -> str:
    """Run `SCRIPT` and return one block per command: the command line, the
    exit code, and the output."""
    blocks: list[str] = []
    with pytest.MonkeyPatch.context() as mp, tempfile.TemporaryDirectory() as tmp:
        files = {
            "@BANK@": str(FIXTURES / "deutsche_bank_statement.csv"),
            "@BROKER@": str(FIXTURES / "simple_broker.csv"),
            "@RULES@": str(Path(tmp) / "rules.toml"),
        }
        Path(files["@RULES@"]).write_text(RULES)
        prices = Path(tmp) / "prices.csv"
        prices.write_text(PRICE_FILE)
        mp.setenv("KOHLE_PRICE_FILE", str(prices))
        mp.setenv("XDG_CONFIG_HOME", str(Path(tmp) / "config"))
        mp.setenv("XDG_DATA_HOME", str(Path(tmp) / "data"))
        mp.setenv("KOHLE_DB", os.path.join(tmp, "unused.db"))

        class PinnedDate(date):
            @classmethod
            def today(cls) -> "PinnedDate":
                return cls(TODAY.year, TODAY.month, TODAY.day)

        mp.setattr("kohle.app.cli.cli.date", PinnedDate)

        runner = CliRunner()
        for args in SCRIPT:
            args = [files.get(a, a) for a in args]
            result = runner.invoke(cli, args, obj=session_factory)
            shown = " ".join(a if not a.startswith("/") else Path(a).name for a in args)
            blocks.append(f"$ {shown}\n[exit {result.exit_code}]\n{result.output}")
    return "\n".join(blocks)
