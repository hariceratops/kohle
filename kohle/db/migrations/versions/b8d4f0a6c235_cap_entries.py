"""cap entries

Adds `cap_entries`, the effective-dated spending-cap history per expense
account.

Revision ID: b8d4f0a6c235
Revises: a7c3e9d5b124
Create Date: 2026-10-31 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d4f0a6c235'
down_revision: str | Sequence[str] | None = 'a7c3e9d5b124'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'cap_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(20, 8), nullable=True),
        sa.Column('rule', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'effective_from', name='uq_cap_entry_account_effective_from'),
        sa.CheckConstraint('(amount IS NULL) = (rule IS NULL)', name='ck_cap_entry_end_is_both_null'),
    )


def _refuse_if_unrepresentable() -> None:
    """The previous schema has no caps, so a ledger holding any cannot go back."""
    held = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM cap_entries")).scalar_one()
    if held:
        raise RuntimeError(
            "Refusing to downgrade: the ledger holds spending caps, and the previous schema "
            "has nowhere to hold them.\n"
            "Back up kohle.db and note them down first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()
    op.drop_table('cap_entries')
