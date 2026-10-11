"""price bindings

Adds `price_bindings` — which plugin and symbol a security's price comes
from (design §4.2). One row per unit; no currency, the plugin reports it.

Revision ID: b3f9d2a41c70
Revises: a1cebfe54f33
Create Date: 2026-10-11 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3f9d2a41c70'
down_revision: str | Sequence[str] | None = 'a1cebfe54f33'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'price_bindings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.Integer(), nullable=False),
        sa.Column('plugin_name', sa.String(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('unit_id', name='uq_price_binding_unit'),
    )


def _refuse_if_unrepresentable() -> None:
    """Bindings are user declarations the ledger cannot reconstruct."""
    conn = op.get_bind()
    bindings = conn.execute(sa.text("SELECT COUNT(*) FROM price_bindings")).scalar() or 0

    if bindings:
        raise RuntimeError(
            f"Refusing to downgrade: {bindings} price binding(s) would be dropped, and the "
            "previous schema has nowhere to hold them.\n"
            "Back up kohle.db and export them first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()
    op.drop_table('price_bindings')
