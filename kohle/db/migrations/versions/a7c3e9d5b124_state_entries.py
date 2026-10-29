"""state entries

Replaces the `state` setting with `state_entries`, the effective-dated
Bundesland history. A stored `state` setting becomes the `start` entry.

Revision ID: a7c3e9d5b124
Revises: f6b2d4c8e013
Create Date: 2026-10-29 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c3e9d5b124'
down_revision: str | Sequence[str] | None = 'f6b2d4c8e013'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# How SQLAlchemy's SQLite Date stores `date.min`, the `start` entry.
START = '0001-01-01'


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'state_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('state', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('effective_from', name='uq_state_entry_effective_from'),
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO state_entries (effective_from, state) "
            "SELECT :start, value FROM settings WHERE key = 'state'"
        ),
        {"start": START},
    )
    conn.execute(sa.text("DELETE FROM settings WHERE key = 'state'"))


def _refuse_if_unrepresentable() -> None:
    """The previous schema holds one state, so a ledger with a move cannot go back."""
    moved = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM state_entries WHERE effective_from <> :start"),
        {"start": START},
    ).scalar_one()
    if moved:
        raise RuntimeError(
            "Refusing to downgrade: the state history has a move after the start, and the "
            "previous schema holds one state only.\n"
            "Back up kohle.db and note the history down first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO settings (key, value) "
            "SELECT 'state', state FROM state_entries WHERE effective_from = :start"
        ),
        {"start": START},
    )
    op.drop_table('state_entries')
