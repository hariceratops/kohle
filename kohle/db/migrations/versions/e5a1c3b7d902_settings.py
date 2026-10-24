"""settings

Adds `settings`, the ledger-wide key/value table. It inserts no rows, so
existing ledgers come out with every setting unset.

Revision ID: e5a1c3b7d902
Revises: d4e7a8c15b92
Create Date: 2026-10-19 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5a1c3b7d902'
down_revision: str | Sequence[str] | None = 'd4e7a8c15b92'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('value', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', name='uq_setting_key'),
    )


def _refuse_if_unrepresentable() -> None:
    """Settings are user declarations the ledger cannot reconstruct."""
    conn = op.get_bind()
    settings = conn.execute(sa.text("SELECT COUNT(*) FROM settings")).scalar() or 0

    if settings:
        raise RuntimeError(
            f"Refusing to downgrade: {settings} setting(s) would be dropped, and the "
            "previous schema has nowhere to hold them.\n"
            "Back up kohle.db and note them down first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()
    op.drop_table('settings')
