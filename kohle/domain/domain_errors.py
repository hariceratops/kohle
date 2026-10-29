from datetime import date
from decimal import Decimal
from pathlib import Path


class AccountError(Exception):
    pass


class AccountNotFoundError(AccountError):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def __str__(self) -> str:
        return f"Account {self.name!r} not found"


class EmptyAccountName(AccountError):
    def __str__(self) -> str:
        return "Account name cannot be empty"


class DuplicateAccountName(AccountError):
    def __init__(self, account_name: str) -> None:
        super().__init__()
        self.account_name = account_name

    def __str__(self) -> str:
        return f"Account {self.account_name} already exists"


class DuplicateIBAN(AccountError):
    def __init__(self, iban: str) -> None:
        super().__init__()
        self.iban = iban

    def __str__(self) -> str:
        return f"IBAN {self.iban} already exists"


class ParentAccountNotFound(AccountError):
    def __init__(self, parent_name: str) -> None:
        super().__init__()
        self.parent_name = parent_name

    def __str__(self) -> str:
        return f"Parent account {self.parent_name} not found"


class UnitError(Exception):
    pass


class UnitNotFoundError(UnitError):
    def __init__(self, identifier: str) -> None:
        super().__init__()
        self.identifier = identifier

    def __str__(self) -> str:
        return f"Unit {self.identifier} not found"


class UnknownInstruments(UnitError):
    def __init__(self, identifiers: list[str]) -> None:
        super().__init__()
        self.identifiers = identifiers

    def __str__(self) -> str:
        names = ", ".join(repr(i) for i in self.identifiers)
        hints = "; ".join(f"kohle-cli add-unit {i} <name>" for i in self.identifiers)
        return f"Unknown instruments: {names}. Add them first, e.g. {hints}"


class NotASecurityUnit(UnitError):
    def __init__(self, identifier: str, kind: str) -> None:
        super().__init__()
        self.identifier = identifier
        self.kind = kind

    def __str__(self) -> str:
        return f"Unit {self.identifier!r} is a {self.kind}, not a security"


class DuplicateUnit(UnitError):
    def __init__(self, identifier: str) -> None:
        super().__init__()
        self.identifier = identifier

    def __str__(self) -> str:
        return f"Unit {self.identifier} already exists"


class EmptyUnitIdentifier(UnitError):
    def __str__(self) -> str:
        return "Unit identifier cannot be empty"


class JournalError(Exception):
    pass


class DuplicateJournalEntry(JournalError):
    def __init__(self, reference: str) -> None:
        super().__init__()
        self.reference = reference

    def __str__(self) -> str:
        return f"Journal entry {self.reference} already exists"


class UnbalancedEntry(JournalError):
    def __init__(self, debit_total, credit_total) -> None:
        super().__init__()
        self.debit_total = debit_total
        self.credit_total = credit_total

    def __str__(self) -> str:
        return f"Entry does not balance: debits {self.debit_total} against credits {self.credit_total}"


class PostingToNonLeafAccount(JournalError):
    """Parent balances are the sum of their children, so a posting that lands on
    a parent silently breaks every rollup."""

    def __init__(self, account_id: int) -> None:
        super().__init__()
        self.account_id = account_id

    def __str__(self) -> str:
        return f"Account id {self.account_id} has children and cannot be posted to directly"


class EmptyEntry(JournalError):
    def __str__(self) -> str:
        return "Journal entry must have at least two lines"


class BaseCurrencyAsCrossUnit(JournalError):
    """--from-unit/--to-unit name a non-base unit only; the base currency is
    the default and needs no unit flag at all."""

    def __str__(self) -> str:
        return "The base currency is the default; omit the unit flags"


class DuplicateLineInEntry(JournalError):
    """Maps `uq_journal_line_entry_account_unit_side`: two --line values on
    the same account, unit and side should be combined into one line rather
    than posted separately (design §5.3)."""

    def __str__(self) -> str:
        return "Two lines on the same account, unit and side; combine them"


class RuleError(Exception):
    pass


class EmptyRulePattern(RuleError):
    """An empty pattern compiles fine and matches every line, which is the one
    catch-all nobody writes on purpose."""

    def __str__(self) -> str:
        return "Rule pattern cannot be empty"


class InvalidRulePattern(RuleError):
    def __init__(self, pattern: str, reason: str) -> None:
        super().__init__()
        self.pattern = pattern
        self.reason = reason

    def __str__(self) -> str:
        return f"Invalid rule pattern {self.pattern!r}: {self.reason}"


class RuleNotFoundError(RuleError):
    def __init__(self, rule_id: int) -> None:
        super().__init__()
        self.rule_id = rule_id

    def __str__(self) -> str:
        return f"Rule id {self.rule_id} not found"


class ClassificationError(Exception):
    pass


class NoClassificationForEntry(ClassificationError):
    """Raised by `reclassify` and `split-line` for an unknown entry id or one
    that was never classified — hand-entered `record`/`record-split` entries
    have no classification row to correct or split."""

    def __init__(self, entry_id: int) -> None:
        super().__init__()
        self.entry_id = entry_id

    def __str__(self) -> str:
        return (
            f"Journal entry id {self.entry_id} has no classification record; "
            "only imported cash lines can be reclassified or split"
        )


class SplitError(Exception):
    pass


class NotAPersonAccount(SplitError):
    """`split-line`'s target must be a leaf under the People branch, not any
    account that happens to resolve by name."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def __str__(self) -> str:
        return f"Account {self.name!r} is not under the People branch"


class SplitDoesNotSumToLine(SplitError):
    """--mine plus every --share must equal the original line's quantity
    exactly — the arithmetic check `--mine` exists to make falsifiable
    (design §4.1)."""

    def __init__(self, line_quantity: Decimal, given: Decimal) -> None:
        super().__init__()
        self.line_quantity = line_quantity
        self.given = given

    def __str__(self) -> str:
        return f"Split shares sum to {self.given}, not the line's {self.line_quantity}"


class EmptySplitGroupName(SplitError):
    def __str__(self) -> str:
        return "Split group name cannot be empty"


class DuplicateSplitGroup(SplitError):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def __str__(self) -> str:
        return f"Split group {self.name} already exists"


class SplitGroupNotFound(SplitError):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def __str__(self) -> str:
        return f"Split group {self.name!r} not found"


class NoSplitForEntry(SplitError):
    def __init__(self, entry_id: int) -> None:
        super().__init__()
        self.entry_id = entry_id

    def __str__(self) -> str:
        return f"Journal entry id {self.entry_id} has no current split"


class EntryAlreadySplit(SplitError):
    """`reclassify` reverses the original line's full quantity out of
    final_account_id; on a split line that account only holds the own
    share, so reclassifying would silently corrupt the balance (design
    §5.4). Refused rather than made split-aware."""

    def __init__(self, entry_id: int) -> None:
        super().__init__()
        self.entry_id = entry_id

    def __str__(self) -> str:
        return (
            f"Journal entry id {self.entry_id} is split; undo the split with "
            f"`unsplit-line {self.entry_id}`, reclassify, then split again"
        )


class InvalidDateError(Exception):
    def __init__(self, date_str: str) -> None:
        super().__init__()
        self.date_str = date_str

    def __str__(self) -> str:
        return f"Unable to parse date from str {self.date_str}"


class EndDatePrecedesStartDateError(Exception):
    def __init__(self, start_date: str, end_date: str) -> None:
        super().__init__()
        self.start_date = start_date
        self.end_date = end_date

    def __str__(self) -> str:
        return f"End date {self.end_date} precedes start_date {self.start_date}"


QueryJournalByPeriodError = \
        InvalidDateError | \
        JournalError | \
        EndDatePrecedesStartDateError | \
        AccountNotFoundError

class MalformedStatementRow(Exception):
    def __init__(self, row_number: int, field: str, problem: str) -> None:
        super().__init__()
        self.row_number = row_number
        self.field = field
        self.problem = problem

    def __str__(self) -> str:
        return f"Statement row {self.row_number}: {self.field} {self.problem}"


class DuplicateReferenceInStatement(Exception):
    def __init__(self, reference: str, first_row_number: int, row_number: int) -> None:
        super().__init__()
        self.reference = reference
        self.first_row_number = first_row_number
        self.row_number = row_number

    def __str__(self) -> str:
        return (
            f"Statement rows {self.first_row_number} and {self.row_number} "
            f"share the reference {self.reference!r}"
        )


class MissingInstrumentAccount(Exception):
    def __str__(self) -> str:
        return "The statement contains trades; name the instrument account they post to"


StatementError = MalformedStatementRow | DuplicateReferenceInStatement | MissingInstrumentAccount

ImportStatementError = \
        StatementError | \
        AccountNotFoundError | \
        JournalError | \
        UnitError | \
        RuleError | \
        ClassificationError

RecordEntryError = AccountError | UnitError | JournalError | BaseCurrencyAsCrossUnit

# JournalError because a rule pointing at a parent account is refused with the
# ledger's own PostingToNonLeafAccount, checked at rule creation rather than at
# the import it would otherwise break.
AddRuleError = AccountError | RuleError | JournalError

BalanceError = AccountError | JournalError

# AccountError survives an infrastructure failure resolving a bucket; the one
# AccountError case the use case actually handles — AccountNotFoundError,
# meaning nothing has ever been imported — is swallowed into an empty list
# rather than reaching here (design §6.2).
ListUnclassifiedError = AccountError | ClassificationError

# JournalError surfaces PostingToNonLeafAccount from validate_lines inside
# post_entry, unchanged and not re-implemented for the adjusting entry
# (design §7.4). SplitError surfaces EntryAlreadySplit, the guard added so
# reclassify refuses a split line rather than silently corrupting it
# (design §5.4).
ReclassifyError = AccountError | JournalError | ClassificationError | SplitError

# JournalError surfaces PostingToNonLeafAccount from validate_lines inside
# post_entry for the adjusting entry, and DuplicateLineInEntry for two
# persons named twice in one invocation (design §4.3).
SplitImportedEntryError = AccountError | JournalError | ClassificationError | SplitError


class PriceError(Exception):
    pass


class UnknownPricePlugin(PriceError):
    def __init__(self, name: str, available: list[str]) -> None:
        super().__init__()
        self.name = name
        self.available = available

    def __str__(self) -> str:
        installed = ", ".join(self.available) if self.available else "none installed"
        return f"Unknown price plugin {self.name!r}. Available: {installed}"


class EmptyPriceSymbol(PriceError):
    def __str__(self) -> str:
        return "Price symbol cannot be empty"


SetPriceSourceError = UnitError | PriceError


class MissingCloseResult(Exception):
    def __init__(self, symbol: str) -> None:
        super().__init__()
        self.symbol = symbol

    def __str__(self) -> str:
        return f"Plugin returned no result for symbol {self.symbol!r}"


class NonPositivePrice(Exception):
    def __init__(self, price: Decimal) -> None:
        super().__init__()
        self.price = price

    def __str__(self) -> str:
        return f"Close price {self.price} must be a positive finite number"


class FutureCloseDate(Exception):
    def __init__(self, price_date: date, today: date) -> None:
        super().__init__()
        self.price_date = price_date
        self.today = today

    def __str__(self) -> str:
        return f"Close dated {self.price_date} is after today ({self.today})"


class NonBaseCurrency(Exception):
    def __init__(self, currency: str, base: str) -> None:
        super().__init__()
        self.currency = currency
        self.base = base

    def __str__(self) -> str:
        return f"Close is in {self.currency!r}, but only {self.base} closes are accepted"


class UnrequestedSymbol(Exception):
    def __init__(self, plugin_name: str, symbol: str) -> None:
        super().__init__()
        self.plugin_name = plugin_name
        self.symbol = symbol

    def __str__(self) -> str:
        return f"Plugin {self.plugin_name!r} returned a result for unrequested symbol {self.symbol!r}; ignored"


PriceRejection = MissingCloseResult | NonPositivePrice | FutureCloseDate | NonBaseCurrency

ListPriceTargetsError = BalanceError | PriceError

ValuationError = BalanceError | PriceError


class LotShortfall(Exception):
    def __init__(self, unit_identifier: str, account_name: str, entry_date: date, shortfall: Decimal) -> None:
        super().__init__()
        self.unit_identifier = unit_identifier
        self.account_name = account_name
        self.entry_date = entry_date
        self.shortfall = shortfall

    def __str__(self) -> str:
        return (
            f"{self.unit_identifier} in {self.account_name!r} on {self.entry_date}: "
            f"disposes of {self.shortfall.normalize():f} more than the account holds; "
            "is an earlier purchase missing?"
        )


class UnbalancedOwnMove(Exception):
    def __init__(
        self, entry_id: int, entry_date: date, unit_identifier: str, moved_out: Decimal, moved_in: Decimal
    ) -> None:
        super().__init__()
        self.entry_id = entry_id
        self.entry_date = entry_date
        self.unit_identifier = unit_identifier
        self.moved_out = moved_out
        self.moved_in = moved_in

    def __str__(self) -> str:
        return (
            f"Entry {self.entry_id} on {self.entry_date} moves {self.moved_out.normalize():f} "
            f"{self.unit_identifier} out of own accounts but {self.moved_in.normalize():f} in; "
            "record the move and any sale or purchase as separate entries"
        )


class SecurityMoveWithPeople(Exception):
    def __init__(
        self, entry_id: int, entry_date: date, unit_identifier: str, own_account: str, people_account: str
    ) -> None:
        super().__init__()
        self.entry_id = entry_id
        self.entry_date = entry_date
        self.unit_identifier = unit_identifier
        self.own_account = own_account
        self.people_account = people_account

    def __str__(self) -> str:
        return (
            f"Entry {self.entry_id} on {self.entry_date} moves {self.unit_identifier} between own account "
            f"{self.own_account!r} and People account {self.people_account!r}; "
            "moving securities to or from people is not supported yet"
        )


LotError = LotShortfall | UnbalancedOwnMove | SecurityMoveWithPeople


RealisedError = BalanceError | LotError

PositionsError = BalanceError | LotError | PriceError


class SettingError(Exception):
    pass


class UnknownSetting(SettingError):
    def __init__(self, key: str, known: list[str]) -> None:
        super().__init__()
        self.key = key
        self.known = known

    def __str__(self) -> str:
        return f"unknown setting {self.key!r}; known settings: {', '.join(self.known)}"


class InvalidSettingValue(SettingError):
    def __init__(self, key: str, value: object, expected: str) -> None:
        super().__init__()
        self.key = key
        self.value = value
        self.expected = expected

    def __str__(self) -> str:
        return f"invalid {self.key} {self.value!r}; expected {self.expected}"


class MissingSettings(SettingError):
    def __init__(self, keys: list[str]) -> None:
        super().__init__()
        self.keys = keys

    def __str__(self) -> str:
        return f"missing {', '.join(self.keys)}"


class SettingDiffers(SettingError):
    def __init__(self, path: Path, key: str, stored: str | None, wanted: str) -> None:
        super().__init__()
        self.path = path
        self.key = key
        self.stored = stored
        self.wanted = wanted

    def __str__(self) -> str:
        setter = f"`kohle-cli set-setting {self.key} {self.wanted}`"
        if self.stored is None:
            return f"ledger at {self.path} has no {self.key}; set it with {setter}"
        return (
            f"ledger at {self.path} has {self.key} = {self.stored} but init.toml says {self.wanted}; "
            f"init never changes an existing ledger, {setter} does"
        )


class StateNotSet(SettingError):
    def __str__(self) -> str:
        return "no state set for this ledger; set it with `kohle-cli set-setting state <code>` or pass --state"


class DeviceKeyNotASetting(SettingError):
    def __init__(self, key: str, config_path: Path) -> None:
        super().__init__()
        self.key = key
        self.config_path = config_path

    def __str__(self) -> str:
        return f"`{self.key}` is a device key; edit {self.config_path}"


class DeviceConfigError(Exception):
    pass


class InvalidDeviceValue(DeviceConfigError):
    def __init__(self, key: str, value: object, expected: str) -> None:
        super().__init__()
        self.key = key
        self.value = value
        self.expected = expected

    def __str__(self) -> str:
        return f"invalid {self.key} {self.value!r}; expected {self.expected}"


class UnknownDeviceKey(DeviceConfigError):
    def __init__(self, key: str, known: list[str]) -> None:
        super().__init__()
        self.key = key
        self.known = known

    def __str__(self) -> str:
        return f"unknown device key {self.key!r}; known device keys: {', '.join(self.known)}"


class BadConfigFile(DeviceConfigError):
    def __init__(self, path: Path, reason: str | UnknownDeviceKey | InvalidDeviceValue) -> None:
        super().__init__()
        self.path = path
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.path}: {self.reason}"


class DeviceIsReader(DeviceConfigError):
    def __init__(self, config_path: Path) -> None:
        super().__init__()
        self.config_path = config_path

    def __str__(self) -> str:
        return f"this device is configured as a reader; `ledger.mode` is set in {self.config_path}"


class RecurrenceError(Exception):
    pass


class InvalidRecurrence(RecurrenceError):
    def __init__(self, text: str, expected: str) -> None:
        super().__init__()
        self.text = text
        self.expected = expected

    def __str__(self) -> str:
        return f"invalid rule {self.text!r}; expected {self.expected}"


class SamplingError(Exception):
    pass


class EmptySamplingRules(SamplingError):
    def __str__(self) -> str:
        return 'no sampling rules given; write "<role>: <rule>; …" with roles mid-month, salary'


class InvalidRole(SamplingError):
    def __init__(self, item: str, role: str | None) -> None:
        super().__init__()
        self.item = item
        self.role = role

    def __str__(self) -> str:
        if self.role is None:
            return f'{self.item!r} has no role; write "<role>: <rule>" with role mid-month or salary'
        return f"unknown role {self.role!r} in {self.item!r}; roles: mid-month, salary"


SamplingRulesError = SamplingError | InvalidRecurrence

HistoryError = ValuationError | SamplingRulesError
