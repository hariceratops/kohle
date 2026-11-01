"""Layer 2/3 — classify-rules (design §17.7)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy.orm import sessionmaker

from kohle.app.cli.cli import cli
from kohle.core.result import Result
from kohle.domain.domain_errors import ClassifyPlanChanged, PostingToNonLeafAccount
from kohle.domain.models import (
    Account,
    AccountType,
    Classification,
    JournalEntry,
    JournalLine,
    Operation,
    OperationGroup,
    Rule,
    Split,
)
from kohle.plugin.importer_plugin import CashRow, StatementImporterPlugin
from kohle.use_cases import classification as classification_module
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.classification import (
    ApplyClassifyRules,
    PlanClassifyRules,
    Reclassify,
)
from kohle.use_cases.journal import PEOPLE_ROOT

BUCKET = "Unclassified Expense"
IBAN = "DE89370400440532013000"


def _rules_file(*rules: tuple[str, str]) -> str:
    """(account, any_field pattern) pairs as a rule file, in priority order."""
    return "".join(
        f'[[rule]]\naccount = "{account}"\n[rule.when]\nany_field = "{pattern}"\n\n' for account, pattern in rules
    )


class _Ledger:
    def __init__(self, session_factory: sessionmaker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sf = session_factory
        self.tmp_path = tmp_path
        self.monkeypatch = monkeypatch
        self.runner = CliRunner()
        for name, kind in (("Cash", "asset"), ("Groceries", "expense"), ("Rent", "expense"),
                           ("Household", "expense"), ("Savings", "expense"), (BUCKET, "expense")):
            self.cli("add-account", name, "--type", kind)
        self.cli("add-unit", "EUR", "Euro", "--kind", "currency")
        self._batches = 0

    def cli(self, *argv: str, **kwargs):
        return self.runner.invoke(cli, list(argv), obj=self.sf, **kwargs)

    def apply_rules(self, text: str) -> None:
        path = self.tmp_path / "rules.toml"
        path.write_text(text)
        result = self.cli("apply-rules", str(path), "--yes")
        assert result.exit_code == 0, result.output

    def import_rows(self, *rows: tuple[str, str, int | str]) -> None:
        """(reference, description, signed amount) rows, all with the same IBAN."""
        cash_rows = [
            CashRow(
                entry_date=date(2026, 3, 1 + position),
                reference=reference,
                description=description,
                amount=Decimal(amount),
                counterparty_name="Partner",
                counterparty_iban=IBAN,
            )
            for position, (reference, description, amount) in enumerate(rows)
        ]

        class _Plugin(StatementImporterPlugin):
            name = "fake"

            def import_statement(self, statement_path: str):
                return Result.ok(cash_rows)

        self.monkeypatch.setattr("kohle.app.cli.cli.load_plugins", lambda: {"fake": _Plugin()})
        statement = self.tmp_path / f"statement-{self._batches}.csv"
        statement.write_text("")
        self._batches += 1
        result = self.cli("import-statement", "fake", "Cash", str(statement))
        assert result.exit_code == 0, result.output

    def entry_id(self, description: str) -> int:
        with self.sf() as session:
            return session.query(JournalEntry).filter(JournalEntry.description == description).one().id

    def classification(self, description: str) -> dict:
        with self.sf() as session:
            row = session.query(Classification).filter(
                Classification.journal_entry_id == self.entry_id(description)
            ).one()
            return {
                "proposed": session.get(Account, row.proposed_account_id).name,
                "matched": row.matched_rule_id,
                "final": session.get(Account, row.final_account_id).name,
                "corrected": row.corrected,
                "rerun": row.rerun_rule_id,
            }

    def rerun_descriptions(self) -> set[str]:
        with self.sf() as session:
            rows = (
                session.query(JournalEntry.description)
                .join(Classification, Classification.journal_entry_id == JournalEntry.id)
                .filter(Classification.rerun_rule_id.is_not(None))
                .all()
            )
            return {description for (description,) in rows}

    def net(self, account: str) -> Decimal:
        """Debits minus credits on the account, in the unit's quantity."""
        with self.sf() as session:
            lines = session.query(JournalLine).join(Account, JournalLine.account_id == Account.id).filter(
                Account.name == account
            ).all()
            return sum((line.value if line.is_debit else -line.value for line in lines), Decimal(0))

    def rule_id(self, account: str) -> int:
        with self.sf() as session:
            return session.query(Rule).join(Account, Rule.account_id == Account.id).filter(
                Account.name == account, Rule.deleted_at.is_(None)
            ).one().id

    def count(self, entity) -> int:
        with self.sf() as session:
            return session.query(entity).count()


@pytest.fixture
def ledger(session_factory: sessionmaker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Ledger:
    return _Ledger(session_factory, tmp_path, monkeypatch)


def test_only_lines_that_fell_through_at_import_and_are_untouched_are_moved(ledger: _Ledger) -> None:
    ledger.apply_rules(_rules_file((BUCKET, "TOBUCKET"), ("Groceries", "AMZN")))
    ledger.import_rows(
        ("r1", "AMZN order", -80),
        ("r2", "TOBUCKET AMZN", -10),
        ("r3", "HUMAN", -20),
        ("r4", "SPLIT", -30),
        ("r5", "MOVEME", -40),
        ("r6", "ALREADY", -50),
        ("r7", "BUCKETONLY", -60),
    )
    AddAccount(ledger.sf()).execute(PEOPLE_ROOT, AccountType.asset)
    assert ledger.cli("reclassify", str(ledger.entry_id("HUMAN")), "Rent").exit_code == 0
    assert ledger.cli("reclassify", str(ledger.entry_id("HUMAN")), BUCKET).exit_code == 0
    # An existing splits row is what makes reclassify refuse a line, and so
    # what the candidate query must also leave alone.
    with ledger.sf() as session:
        session.add(Split(journal_entry_id=ledger.entry_id("SPLIT"), adjusting_entry_id=None))
        session.commit()
    ledger.apply_rules(_rules_file(
        ("Household", "AMZN"), ("Household", "HUMAN"), ("Household", "SPLIT"),
        ("Rent", "ALREADY"), ("Groceries", "MOVEME"), (BUCKET, "BUCKETONLY"),
    ))

    result = ledger.cli("classify-rules", "--yes")

    assert result.exit_code == 0, result.output
    assert ledger.rerun_descriptions() == {"MOVEME", "ALREADY"}
    assert result.output.splitlines()[-1] == "Moved 2 line(s)"
    assert ledger.classification("AMZN order")["final"] == "Groceries"
    assert ledger.classification("TOBUCKET AMZN")["final"] == BUCKET
    assert ledger.classification("HUMAN")["final"] == BUCKET
    assert ledger.classification("SPLIT")["final"] == BUCKET
    assert ledger.classification("BUCKETONLY")["final"] == BUCKET
    again = ledger.cli("classify-rules", "--yes")
    assert again.output == "No unclassified line matches a rule\n"


def test_a_move_is_recorded_without_touching_proposed_matched_or_corrected(ledger: _Ledger) -> None:
    ledger.import_rows(("r1", "MOVEME", -40))
    ledger.apply_rules(_rules_file(("Groceries", "MOVEME")))
    before = ledger.classification("MOVEME")

    assert ledger.cli("classify-rules", "--yes").exit_code == 0

    after = ledger.classification("MOVEME")
    assert before == {"proposed": BUCKET, "matched": None, "final": BUCKET, "corrected": False, "rerun": None}
    assert after == {
        "proposed": BUCKET, "matched": None, "final": "Groceries", "corrected": False,
        "rerun": ledger.rule_id("Groceries"),
    }


def test_the_correcting_entry_is_dated_at_the_original_and_balances_as_reclassify_would(ledger: _Ledger) -> None:
    ledger.import_rows(("r1", "MOVEME", -40), ("r2", "HUMAN", -40))
    ledger.apply_rules(_rules_file(("Groceries", "MOVEME")))

    assert ledger.cli("classify-rules", "--yes").exit_code == 0
    assert ledger.cli("reclassify", str(ledger.entry_id("HUMAN")), "Groceries").exit_code == 0

    with ledger.sf() as session:
        original = session.query(JournalEntry).filter(JournalEntry.description == "MOVEME").one()
        correcting = session.query(JournalEntry).filter(JournalEntry.description == "Classify: MOVEME").one()
        assert correcting.entry_date == original.entry_date == date(2026, 3, 1)
    assert ledger.net(BUCKET) == Decimal(0)
    assert ledger.net("Groceries") == Decimal(80)


def test_a_moved_line_can_still_be_reclassified_and_split(ledger: _Ledger) -> None:
    ledger.import_rows(("r1", "MOVEME", -40), ("r2", "ALSO", -40))
    ledger.apply_rules(_rules_file(("Groceries", "MOVEME"), ("Household", "ALSO")))
    assert ledger.cli("classify-rules", "--yes").exit_code == 0
    assert AddAccount(ledger.sf()).execute(PEOPLE_ROOT, AccountType.asset).is_ok
    assert AddAccount(ledger.sf()).execute("Anna", AccountType.asset, None, PEOPLE_ROOT).is_ok

    reclassified = ledger.cli("reclassify", str(ledger.entry_id("MOVEME")), "Rent")
    split = ledger.cli("split-line", str(ledger.entry_id("ALSO")), "--mine", "15", "--share", "Anna:25")

    assert reclassified.exit_code == 0, reclassified.output
    assert split.exit_code == 0, split.output
    moved = ledger.classification("MOVEME")
    assert (moved["final"], moved["corrected"], moved["rerun"]) == ("Rent", True, ledger.rule_id("Groceries"))
    # Reversed out of the rule's target (MOVEME fully, ALSO by Anna's share),
    # never out of the bucket a second time.
    assert ledger.net(BUCKET) == Decimal(0)
    assert ledger.net("Rent") == Decimal(40)
    assert ledger.net("Groceries") == Decimal(0)
    assert ledger.net("Household") == Decimal(15)
    assert ledger.net("Anna") == Decimal(25)


def test_an_amount_and_direction_rule_matches_a_past_outgoing_line_as_at_import(ledger: _Ledger) -> None:
    ledger.import_rows(
        ("r1", "Transfer 500", -500), ("r2", "Transfer 2000", -2000), ("r3", "Refund 500", 500),
    )
    ledger.apply_rules(
        f'[[rule]]\naccount = "Household"\n[rule.when]\niban = "{IBAN}"\n'
        'amount = { min = 400, max = 600 }\ndirection = "out"\n\n'
        f'[[rule]]\naccount = "Savings"\n[rule.when]\niban = "{IBAN}"\n'
        'amount = { min = 1500 }\ndirection = "out"\n'
    )

    result = ledger.cli("classify-rules", "--yes")

    assert result.exit_code == 0, result.output
    assert ledger.classification("Transfer 500")["final"] == "Household"
    assert ledger.classification("Transfer 2000")["final"] == "Savings"
    assert ledger.classification("Refund 500")["final"] == "Unclassified Income"
    assert ledger.rerun_descriptions() == {"Transfer 500", "Transfer 2000"}


def _moves_ready(ledger: _Ledger) -> None:
    ledger.import_rows(("r1", "ONE", -10), ("r2", "TWO", -20))
    ledger.apply_rules(_rules_file(("Groceries", "ONE"), ("Rent", "TWO")))


def test_one_operation_group_holds_every_write(ledger: _Ledger) -> None:
    _moves_ready(ledger)
    groups = ledger.count(OperationGroup)

    assert ledger.cli("classify-rules", "--yes").exit_code == 0

    assert ledger.count(OperationGroup) == groups + 1
    with ledger.sf() as session:
        ops = session.query(Operation).filter(Operation.group_id > groups).all()
    assert sorted((op.entity_type, op.action) for op in ops) == [
        ("classifications", "update"), ("classifications", "update"),
        ("journal_entries", "create"), ("journal_entries", "create"),
    ]


def test_a_fault_on_the_second_move_rolls_the_first_back(ledger: _Ledger) -> None:
    _moves_ready(ledger)
    moves = PlanClassifyRules(ledger.sf()).execute().unwrap()
    real = classification_module.set_rerun_outcome_service
    calls = []

    def flaky(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            return Result.err(classification_module.ClassifyPlanChanged())
        return real(*args, **kwargs)

    ledger.monkeypatch.setattr(classification_module, "set_rerun_outcome_service", flaky)
    entries = ledger.count(JournalEntry)
    groups = ledger.count(OperationGroup)

    result = ApplyClassifyRules(ledger.sf()).execute(moves)

    assert result.is_err and len(calls) == 2
    assert ledger.count(JournalEntry) == entries
    assert ledger.count(OperationGroup) == groups
    assert ledger.rerun_descriptions() == set()
    assert ledger.classification("ONE")["final"] == BUCKET


def test_a_line_moved_between_preview_and_apply_gives_classify_plan_changed(ledger: _Ledger) -> None:
    _moves_ready(ledger)
    moves = PlanClassifyRules(ledger.sf()).execute().unwrap()
    assert Reclassify(ledger.sf()).execute(ledger.entry_id("ONE"), "Household").is_ok
    entries = ledger.count(JournalEntry)

    result = ApplyClassifyRules(ledger.sf()).execute(moves)

    assert isinstance(result.unwrap_err(), ClassifyPlanChanged)
    assert ledger.count(JournalEntry) == entries
    assert ledger.rerun_descriptions() == set()


def test_a_target_that_gained_a_child_fails_at_plan_before_any_preview(ledger: _Ledger) -> None:
    _moves_ready(ledger)
    assert AddAccount(ledger.sf()).execute("Food", AccountType.expense, None, "Groceries").is_ok

    planned = PlanClassifyRules(ledger.sf()).execute()
    cli_result = ledger.cli("classify-rules", "--yes")

    assert isinstance(planned.unwrap_err(), PostingToNonLeafAccount)
    assert cli_result.exit_code == 1
    assert "cannot be posted to directly" in cli_result.output
    assert "entry_id" not in cli_result.output
    assert ledger.rerun_descriptions() == set()


def test_the_preview_lists_each_move_and_declining_writes_nothing(ledger: _Ledger) -> None:
    _moves_ready(ledger)
    entries = ledger.count(JournalEntry)
    groups = ledger.count(OperationGroup)

    result = ledger.cli("classify-rules", input="n\n")

    assert result.exit_code == 1
    assert result.output.splitlines()[0].split() == ["entry_id", "date", "description", "amount", "from", "to", "rule"]
    assert " ".join(result.output.splitlines()[2].split()) == (
        f"{ledger.entry_id('ONE')} 2026-03-01 ONE -10.00 {BUCKET} Groceries {ledger.rule_id('Groceries')}"
    )
    assert "Move 2 line(s)?" in result.output
    assert "Aborted!" in result.output
    assert ledger.count(JournalEntry) == entries
    assert ledger.count(OperationGroup) == groups


def test_confirming_applies_and_an_empty_plan_says_so(ledger: _Ledger) -> None:
    assert ledger.cli("classify-rules").output == "No unclassified line matches a rule\n"
    _moves_ready(ledger)

    result = ledger.cli("classify-rules", input="y\n")

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-1] == "Moved 2 line(s)"
    assert ledger.rerun_descriptions() == {"ONE", "TWO"}


def test_changing_rules_never_reclassifies_anything(ledger: _Ledger) -> None:
    ledger.import_rows(("r1", "ONE", -10))
    entries = ledger.count(JournalEntry)
    classifications = ledger.count(Classification)

    ledger.apply_rules(_rules_file(("Groceries", "ONE")))
    assert ledger.cli("add-rule", "TWO", "Rent").exit_code == 0
    assert ledger.cli("remove-rule", "2").exit_code == 0

    assert ledger.count(JournalEntry) == entries
    assert ledger.count(Classification) == classifications
    assert ledger.classification("ONE")["final"] == BUCKET
    assert ledger.rerun_descriptions() == set()
