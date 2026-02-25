from dataclasses import dataclass, field
from typing import Optional
from io import StringIO
import pandas as pd
import numpy as np
from statemachine import StateMachine, State
from kohle.core.result import Result
from kohle.plugin.importer_plugin import StatementImporterPlugin, ImportError
from pyparsing import Literal, Regex, Suppress, StringEnd, DelimitedList
from decimal import Decimal
import numbers


semicolon = Suppress(";")

date = Regex(r"\d{1,2}/\d{1,2}/\d{4}")
amount = Regex(r"-?\d+(?:,\d+)?(?:\.\d+)?")

account_line = (
    Literal("AktivKonto")
    + semicolon
    + Regex(r"\d+\s+\d+\s+\d+")("account_number")
    + semicolon
    + Regex(r"[A-Z]{2}\d+")("iban")
    + semicolon
    + Literal("EUR")("currency")
)

period_line = (
    date("period_start")
    + Suppress("-")
    + date("period_end")
)

old_balance_line = (
    Literal("Old balance")
    + Suppress(";;;;")
    + amount("old_balance")
    + semicolon
    + Literal("EUR")
)

pending_notice_line = Literal(
    "Transactions pending are not included in this report."
)

column = Regex(r"[^;]+")
csv_header = DelimitedList(column, delim=";", min=18, max=18) + StringEnd()
expected_columns = [
    "Booking date",
    "Value date",
    "Transaction Type",
    "Beneficiary / Originator",
    "Payment Details",
    "IBAN / Account Number",
    "BIC",
    "Customer Reference",
    "Mandate Reference",
    "Creditor ID",
    "Compensation amount",
    "Original Amount",
    "Ultimate creditor",
    "Number of transactions",
    "Number of cheques",
    "Debit",
    "Credit",
    "Currency",
]

closing_balance_line = (
    Literal("Account balance")
    + semicolon
    + date("closing_date")
    + Suppress(";;;")
    + amount("closing_balance")
    + semicolon
    + Literal("EUR")
)

# class ImportError:
#     pass


class MissingFieldError(ImportError):
    def __init__(self, field: str):
        self.field = field

    def __str__(self) -> str:
        return f"Field {self.field} is missing"


class MissingSectionError(ImportError):
    def __init__(self, section: str):
        self.section = section


class InvalidStructureError(ImportError):
    def __init__(self, message: str):
        self.message = message


class CsvError(ImportError):
    def __init__(self, message: str):
        self.message = message


@dataclass
class StatementData:
    account_number: str
    iban: str
    currency: str
    period_start: str
    period_end: str
    old_balance: str
    closing_date: str
    closing_balance: str
    transactions: pd.DataFrame


@dataclass
class ParserContext:
    data: dict = field(default_factory=dict)
    table_start: Optional[int] = None
    table_end: Optional[int] = None
    lines: list[str] = field(default_factory=list)


class StatementStateMachine(StateMachine):
    init = State(initial=True)
    meta = State()
    csv = State()
    done = State(final=True)

    to_meta = init.to(meta)
    to_csv = meta.to(csv)
    to_done = csv.to(done)


class StatementParser:
    def __init__(self):
        self.sm = StatementStateMachine()
        self.ctx = ParserContext()

    def parse(self, text: str) -> Result[StatementData, ImportError]:
        self.ctx = ParserContext()
        self.sm = StatementStateMachine()
        self.ctx.lines = text.splitlines()

        for idx, raw_line in enumerate(self.ctx.lines):
            line = raw_line.strip()
            if not line:
                continue

            result = self._dispatch_line(idx, line)
            if result.is_err:
                return Result.err(result.unwrap_err())

            if self.sm.current_state == self.sm.done:
                break

        return self._finalize()

    def _dispatch_line(self, idx: int, line: str) -> Result[None, ImportError]:
        state = self.sm.current_state

        if state == self.sm.init:
            return self._handle_init(line)

        if state == self.sm.meta:
            return self._handle_meta(idx, line)

        if state == self.sm.csv:
            return self._handle_csv(idx, line)

        return Result.ok(None)

    def _handle_init(self, line: str) -> Result[None, ImportError]:
        if account_line.matches(line):
            self.ctx.data.update(account_line.parse_string(line).as_dict())
            self.sm.to_meta()
        return Result.ok(None)

    def _handle_meta(self, idx: int, line: str) -> Result[None, ImportError]:
        if csv_header.matches(line):
            parsed = csv_header.parse_string(line).as_list()
            if parsed != expected_columns:
                return Result.err(InvalidStructureError("Unexpected CSV header structure"))
            self.ctx.table_start = idx
            self.sm.to_csv()
            return Result.ok(None)

        if period_line.matches(line):
            self.ctx.data.update(period_line.parse_string(line).as_dict())
            return Result.ok(None)

        if old_balance_line.matches(line):
            self.ctx.data.update(old_balance_line.parse_string(line).as_dict())
            return Result.ok(None)

        if pending_notice_line.matches(line):
            self.ctx.data["pending_notice"] = True
            return Result.ok(None)

        return Result.ok(None)

    def _handle_csv(self, idx: int, line: str) -> Result[None, ImportError]:
        if closing_balance_line.matches(line):
            self.ctx.data.update(closing_balance_line.parse_string(line).as_dict())
            self.ctx.table_end = idx
            self.sm.to_done()
            return Result.ok(None)

        return Result.ok(None)

    def _finalize(self) -> Result[StatementData, ImportError]:
        validation = self._validate_required()
        if validation.is_err:
            return Result.err(validation.unwrap_err())

        table_result = self._extract_table()
        if table_result.is_err:
            return Result.err(table_result.unwrap_err())

        df = table_result.unwrap()

        statement = StatementData(
            account_number=self.ctx.data["account_number"],
            iban=self.ctx.data["iban"],
            currency=self.ctx.data["currency"],
            period_start=self.ctx.data["period_start"],
            period_end=self.ctx.data["period_end"],
            old_balance=self.ctx.data["old_balance"],
            closing_date=self.ctx.data["closing_date"],
            closing_balance=self.ctx.data["closing_balance"],
            transactions=df,
        )

        return Result.ok(statement)

    def _validate_required(self) -> Result[None, ImportError]:
        required = [
            "account_number",
            "iban",
            "currency",
            "period_start",
            "period_end",
            "old_balance",
            "closing_date",
            "closing_balance",
        ]

        for field in required:
            if field not in self.ctx.data:
                return Result.err(MissingFieldError(field))

        if self.ctx.table_start is None:
            return Result.err(MissingSectionError("CSV header"))

        if self.ctx.table_end is None:
            return Result.err(MissingSectionError("Closing balance"))

        if self.sm.current_state != self.sm.done:
            return Result.err(InvalidStructureError("Parsing incomplete"))

        return Result.ok(None)

    def _extract_table(self) -> Result[pd.DataFrame, ImportError]:
        try:
            table_text = "\n".join(
                self.ctx.lines[self.ctx.table_start:self.ctx.table_end]
            )
            df = pd.read_csv(StringIO(table_text), sep=";", encoding='ISO-8859-1')
            return Result.ok(df)
        except Exception as e:
            return Result.err(CsvError(str(e)))


description_date_pattern = (
    r"(\d{2}-\d{2}-\d{4}T\d{2}:\d{2}:\d{2})"
)


def parse_amount(raw) -> Optional[Decimal]:
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, numbers.Number):
        return Decimal(str(raw))
    if isinstance(raw, str):
        cleaned = raw.strip().replace(",", "")
        return Decimal(cleaned)
    return None


class DeustcheBankStatementImporter(StatementImporterPlugin):
    @property
    def name(self) -> str:
        return "kohle-deutsche-bank"

    def import_statement(self, statement_path) -> Result[pd.DataFrame, ImportError]:
        with open(statement_path, "r") as f:
            parsing_res = StatementParser().parse(f.read())
            if parsing_res.is_err:
                return Result.err(parsing_res.unwrap_err())

            statement_data = parsing_res.unwrap()
            df = statement_data.transactions.\
                    pipe(lambda df: df.rename(columns={
                       'Beneficiary / Originator': 'beneficiary',
                       'Payment Details': 'description',
                       'Debit': 'debit',
                       'Credit': 'credit',
                       'IBAN / Account Number': 'iban',
                       'Booking date': 'booking_date',
                       'Value date': 'value_date',
                       'Transaction Type': 'transaction_type',
                       'BIC': 'bic',
                       'Customer Reference': 'customer_reference',
                       'Mandate Reference': 'mandate_reference',
                       'Creditor ID': 'creditor_id',
                       'Compensation amount': 'compensation_amount',
                       'Original Amount': 'original_amount',
                       'Ultimate creditor': 'ultimate_creditor',
                       'Number of transactions': 'number_of_transactions',
                       'Number of cheques': 'number_of_cheques',
                       'Currency': 'currency'
                   })) \
                   .assign(
                        date=lambda d: np.where(
                            d["transaction_type"] == "Debit Card Payment",
                            pd.to_datetime(
                                d["description"].str.extract(description_date_pattern)[0],
                                format="%d-%m-%YT%H:%M:%S",
                                errors="raise",
                            ),
                            pd.to_datetime(d["booking_date"]),
                        )
                    ) \
                   .fillna({ 'debit': 0, 'credit': 0 }) \
                   .pipe(lambda d: d.assign(amount=np.where(d["debit"] != 0, d["debit"], d["credit"]))) \
                   .pipe(lambda d: d.assign(amount=d["amount"].apply(parse_amount))) \
                   .drop(columns=[
                        'beneficiary', 'transaction_type', 'booking_date',
                        'bic', 'customer_reference', 'mandate_reference', 'creditor_id',
                        'compensation_amount', 'original_amount', 'ultimate_creditor',
                        'number_of_transactions', 'number_of_cheques', "debit", "credit",
                        "currency",
                    ])\
                    .astype({"amount": float})
            
            return Result.ok(df)

