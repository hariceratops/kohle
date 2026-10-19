"""multi unit ledger

Replaces the single-currency transactions table and the standalone debit
categories with a multi-unit double-entry ledger. Expense categories become
accounts; every posting carries a unit and the price it had at the time.

Revision ID: 7f3c1d9a2b40
Revises: 62313518700b
Create Date: 2026-08-31 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7f3c1d9a2b40'
down_revision: str | Sequence[str] | None = '62313518700b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ACCOUNT_TYPE = sa.Enum('asset', 'liability', 'income', 'expense', name='accounttype')
UNIT_KIND = sa.Enum('currency', 'security', 'commodity', name='unitkind')
QUANTITY = sa.Numeric(precision=20, scale=8)


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table('transactions')
    op.drop_table('debit_categories')

    # SQLite cannot add a NOT NULL column with a foreign key or relax a column
    # to nullable in place, so accounts is rebuilt and copied. Existing rows are
    # bank accounts, hence the asset default.
    op.create_table(
        'accounts_new',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('type', ACCOUNT_TYPE, nullable=False),
        sa.Column('iban', sa.String(), nullable=True),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['parent_id'], ['accounts_new.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_account_name'),
        sa.UniqueConstraint('iban', name='uq_account_iban'),
    )
    op.execute(
        "INSERT INTO accounts_new (id, name, type, iban, parent_id, created_at, deleted_at) "
        "SELECT id, name, 'asset', iban, NULL, created_at, deleted_at FROM accounts"
    )
    op.drop_table('accounts')
    op.rename_table('accounts_new', 'accounts')

    op.create_table(
        'units',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', UNIT_KIND, nullable=False),
        sa.Column('identifier', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('identifier', name='uq_unit_identifier'),
    )

    op.create_table(
        'journal_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('reference', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reference', name='uq_journal_entry_reference'),
    )

    op.create_table(
        'journal_lines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entry_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.Integer(), nullable=False),
        sa.Column('quantity', QUANTITY, nullable=False),
        sa.Column('unit_price', QUANTITY, nullable=False),
        sa.Column('is_debit', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['entry_id'], ['journal_entries.id'], ),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'entry_id', 'account_id', 'unit_id', 'is_debit',
            name='uq_journal_line_entry_account_unit_side',
        ),
    )

    op.create_table(
        'prices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.Integer(), nullable=False),
        sa.Column('price_date', sa.Date(), nullable=False),
        sa.Column('price', QUANTITY, nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('unit_id', 'price_date', 'source', name='uq_price_unit_date_source'),
    )


def _refuse_if_unrepresentable() -> None:
    """The old schema cannot hold most of what the new one can. Rather than
    drop that data quietly, refuse and say what would be lost.

    Synthesising placeholder IBANs to satisfy the old NOT NULL constraint was
    considered and rejected: it writes a value that is not the account's IBAN
    into the column the importer matches statements on.
    """
    conn = op.get_bind()

    def count(sql: str) -> int:
        return conn.execute(sa.text(sql)).scalar() or 0

    losses = []
    without_iban = count("SELECT COUNT(*) FROM accounts WHERE iban IS NULL")
    if without_iban:
        losses.append(
            f"{without_iban} account(s) have no IBAN, which the old schema "
            "requires and requires to be unique"
        )
    children = count("SELECT COUNT(*) FROM accounts WHERE parent_id IS NOT NULL")
    if children:
        losses.append(f"{children} account(s) have a parent, which the old schema cannot express")
    entries = count("SELECT COUNT(*) FROM journal_entries")
    if entries:
        losses.append(f"{entries} journal entrie(s) have no equivalent in the old transactions table")
    units = count("SELECT COUNT(*) FROM units WHERE identifier <> 'EUR'")
    if units:
        losses.append(f"{units} non-EUR unit(s) have nowhere to go in a single-currency schema")

    if losses:
        raise RuntimeError(
            "Refusing to downgrade: this would discard data the old schema cannot hold.\n  - "
            + "\n  - ".join(losses)
            + "\nBack up kohle.db and remove or export this data first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    op.drop_table('prices')
    op.drop_table('journal_lines')
    op.drop_table('journal_entries')
    op.drop_table('units')

    op.create_table(
        'accounts_old',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('iban', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('iban', name='uq_account_iban'),
        sa.UniqueConstraint('name', name='uq_account_name'),
    )
    # No COALESCE and no parent filter: _refuse_if_unrepresentable has already
    # established every account has an IBAN and no parent, so anything those
    # would paper over is a bug rather than a case to handle.
    op.execute(
        "INSERT INTO accounts_old (id, name, iban, created_at, deleted_at) "
        "SELECT id, name, iban, created_at, deleted_at FROM accounts"
    )
    op.drop_table('accounts')
    op.rename_table('accounts_old', 'accounts')

    op.create_table(
        'debit_categories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('category', name='uq_debit_category_category'),
    )
    op.create_table(
        'transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('hash', sa.String(length=64), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hash', name='uq_transaction_hash'),
    )
