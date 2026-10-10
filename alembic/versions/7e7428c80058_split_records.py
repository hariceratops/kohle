"""split records

One row per split imported line: the entry it links back to and the
adjusting entry that currently effects the split (design §4.4). No
`group_id` yet — that column lands with `split_groups` (design §10.2).

Revision ID: 7e7428c80058
Revises: d4a2e6f0b917
Create Date: 2026-09-14 13:38:59.832322

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7e7428c80058'
down_revision: str | Sequence[str] | None = 'd4a2e6f0b917'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'splits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('journal_entry_id', sa.Integer(), nullable=False),
        sa.Column('adjusting_entry_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id']),
        sa.ForeignKeyConstraint(['adjusting_entry_id'], ['journal_entries.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('journal_entry_id', name='uq_split_journal_entry'),
    )


def _refuse_if_unrepresentable() -> None:
    """Dropping a populated splits table loses the link between every
    imported line and the entry that split it — the entries survive, but
    which of them is a split, and of what, does not. Count it first and
    refuse rather than lose it quietly."""
    conn = op.get_bind()

    splits = conn.execute(sa.text("SELECT COUNT(*) FROM splits")).scalar() or 0

    if splits:
        raise RuntimeError(
            f"Refusing to downgrade: {splits} split record(s) would be dropped, and the "
            "previous schema has nowhere to hold them.\n"
            "Back up kohle.db and export them first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    op.drop_table('splits')
