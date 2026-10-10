from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from kohle.db.connection import base
from kohle.infrastructure.model_serde import PassAll, PassId, SerdePolicy

# Quantities span cash (2dp) and fractional units of securities and gold, so the
# scale is set by the latter.
QUANTITY = Numeric(20, 8)


class RegisteredBase(DeclarativeBase):
    __abstract__ = True

    @classmethod
    def __get_policy__(cls) -> SerdePolicy:
        mapper = cls.__mapper__
        relations: dict[str, SerdePolicy] = {r.key: SerdePolicy(PassId(), {}) for r in mapper.relationships}
        return SerdePolicy(PassAll(), relations)


class Archivable:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OperationGroup(base):
    __tablename__ = "operation_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Operation(base):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("operation_groups.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    field: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str | None] = mapped_column(String, nullable=True)

    def __eq__(self, other) -> bool:
        return self.group_id == other.group_id and \
               self.entity_type == other.entity_type and \
               self.entity_id == other.entity_id and \
               self.action == other.action and \
               self.field == other.field and \
               self.state == other.state


class AccountType(Enum):
    asset = "asset"
    liability = "liability"
    income = "income"
    expense = "expense"


class UnitKind(Enum):
    currency = "currency"
    security = "security"
    commodity = "commodity"


class Unit(base, Archivable):
    """What a quantity is denominated in: EUR, an ISIN, grams of gold."""

    __tablename__ = "units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[UnitKind] = mapped_column(SqlEnum(UnitKind), nullable=False)
    identifier: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("identifier", name="uq_unit_identifier"),
    )

    def __eq__(self, other) -> bool:
        return isinstance(other, Unit) and self.id == other.id and self.identifier == other.identifier

    def __repr__(self) -> str:
        return f"<Unit(id={self.id}, identifier={self.identifier}, kind={self.kind})>"


class Account(base, Archivable):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[AccountType] = mapped_column(SqlEnum(AccountType), nullable=False)
    iban: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    parent: Mapped["Account | None"] = relationship("Account", remote_side=[id], back_populates="children")
    children: Mapped[list["Account"]] = relationship("Account", back_populates="parent")

    # Globally unique rather than unique-per-parent: lookup is by bare name, and
    # a (name, parent_id) constraint would not constrain roots at all, since SQL
    # treats NULL parents as distinct. Scoping names to their parent needs
    # qualified paths (Assets:Checking:Holiday) to look up by.
    __table_args__ = (
        UniqueConstraint("name", name="uq_account_name"),
        UniqueConstraint("iban", name="uq_account_iban"),
    )

    def __eq__(self, other) -> bool:
        return isinstance(other, Account) and self.id == other.id and self.name == other.name and self.iban == other.iban

    def __repr__(self) -> str:
        return f"<Account(id={self.id}, name={self.name}, type={self.type}, iban={self.iban})>"


class JournalEntry(base, Archivable):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    reference: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    # What the bank said about the other side of an imported movement. NULL for
    # hand-entered rows, which have no counterparty concept — a placeholder like
    # '' or 'unknown' would be a value a classification rule could match by
    # accident, and NULL cannot be.
    counterparty_name: Mapped[str | None] = mapped_column(String, nullable=True)
    counterparty_iban: Mapped[str | None] = mapped_column(String, nullable=True)
    lines: Mapped[list["JournalLine"]] = relationship(
        "JournalLine", back_populates="entry", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("reference", name="uq_journal_entry_reference"),
    )

    def __eq__(self, other) -> bool:
        return isinstance(other, JournalEntry) and self.id == other.id and self.reference == other.reference

    def __repr__(self) -> str:
        return f"<JournalEntry(id={self.id}, reference={self.reference}, date={self.entry_date})>"


class JournalLine(base, Archivable):
    __tablename__ = "journal_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    # What one unit cost in the base currency at the time of the transaction.
    # Cash in the base currency is 1, which is what lets cash and asset lines
    # share one shape.
    unit_price: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    is_debit: Mapped[bool] = mapped_column(Boolean, nullable=False)

    entry: Mapped["JournalEntry"] = relationship("JournalEntry", back_populates="lines")
    account: Mapped["Account"] = relationship("Account")
    unit: Mapped["Unit"] = relationship("Unit")

    __table_args__ = (
        UniqueConstraint("entry_id", "account_id", "unit_id", "is_debit", name="uq_journal_line_entry_account_unit_side"),
    )

    @property
    def value(self) -> Decimal:
        return self.quantity * self.unit_price

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, JournalLine)
            and self.id == other.id
            and self.entry_id == other.entry_id
            and self.account_id == other.account_id
            and self.unit_id == other.unit_id
            and self.quantity == other.quantity
            and self.unit_price == other.unit_price
            and self.is_debit == other.is_debit
        )

    def __repr__(self) -> str:
        side = "dr" if self.is_debit else "cr"
        return f"<JournalLine(id={self.id}, entry_id={self.entry_id}, account_id={self.account_id}, {side} {self.quantity}@{self.unit_price})>"


DEFAULT_RULE_PRIORITY = 100


class Rule(base, Archivable):
    """Sends an imported line to an account when its pattern matches the line's
    description or either counterparty field."""

    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern: Mapped[str] = mapped_column(String, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    # Sparse default, so a rule can be inserted either side of an existing one
    # without renumbering the set.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=DEFAULT_RULE_PRIORITY)

    account: Mapped["Account"] = relationship("Account")

    # Deliberately unconstrained: retired rules stay in the table, so a unique
    # pattern would stop a retired rule from being recreated, and a duplicate
    # rule is dead weight rather than a conflict — first match wins.

    def __repr__(self) -> str:
        return f"<Rule(id={self.id}, pattern={self.pattern!r}, priority={self.priority}, account_id={self.account_id})>"


class Classification(base, Archivable):
    """What the classifier proposed for an imported line and where it ended up.

    The labelled record a later ML phase trains on, which is why it is written
    from the first line ever classified: it cannot be reconstructed from the
    ledger afterwards. At import both account columns hold the same value on
    both paths — they diverge only when a human corrects the line, and that
    divergence is the entire record, so they must not be collapsed into one.
    """

    __tablename__ = "classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), nullable=False)
    proposed_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    # NULL means no rule matched and the line fell through to a bucket — a
    # meaningful value rather than a tombstone, which is why a removed rule is
    # retired rather than deleted.
    matched_rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id"), nullable=True)
    final_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    # Not derivable from proposed != final: correcting a line back onto the
    # account it started on leaves them equal on a row a human did touch.
    corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    entry: Mapped["JournalEntry"] = relationship("JournalEntry")
    matched_rule: Mapped["Rule | None"] = relationship("Rule")
    # Only the final account gets a relationship; the proposed one is never
    # displayed, and an unused relationship is a lazy load waiting to fire
    # after the session has closed. Both sides need foreign_keys= because they
    # point at the same table.
    final_account: Mapped["Account"] = relationship("Account", foreign_keys=[final_account_id])

    # One classification per entry, so "the classification of this line" has a
    # single referent: correcting one is an update rather than an append, and a
    # read needs no max-per-entry subquery.
    __table_args__ = (
        UniqueConstraint("journal_entry_id", name="uq_classification_journal_entry"),
    )

    def __repr__(self) -> str:
        return (
            f"<Classification(id={self.id}, entry_id={self.journal_entry_id}, "
            f"rule_id={self.matched_rule_id}, final_account_id={self.final_account_id})>"
        )


class Price(base):
    """Fetched valuation for a unit on a date. Written by price plugins, read
    only by reporting — never by transaction recording."""

    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    price: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)

    unit: Mapped["Unit"] = relationship("Unit")

    __table_args__ = (
        UniqueConstraint("unit_id", "price_date", "source", name="uq_price_unit_date_source"),
    )

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, Price)
            and self.unit_id == other.unit_id
            and self.price_date == other.price_date
            and self.source == other.source
        )

    def __repr__(self) -> str:
        return f"<Price(unit_id={self.unit_id}, date={self.price_date}, price={self.price})>"
