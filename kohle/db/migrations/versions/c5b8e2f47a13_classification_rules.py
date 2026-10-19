"""classification rules

A rule sends an imported line to an account when its pattern matches. Nothing
matches on them yet — the import loop picks them up in the next slice.

Revision ID: c5b8e2f47a13
Revises: a1d7c4e9b208
Create Date: 2026-09-11 09:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c5b8e2f47a13'
down_revision: str | Sequence[str] | None = 'a1d7c4e9b208'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pattern', sa.String(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def _refuse_if_unrepresentable() -> None:
    """Dropping the table discards the user's rule set, which nothing else in
    the database holds. Count it first and refuse rather than lose it quietly."""
    conn = op.get_bind()

    # Retired rules count: their pattern text is what keeps a past
    # classification interpretable, so they are not free to drop either.
    rules = conn.execute(sa.text("SELECT COUNT(*) FROM rules")).scalar() or 0

    if rules:
        raise RuntimeError(
            f"Refusing to downgrade: {rules} classification rule(s) would be dropped, "
            "and the previous schema has nowhere to hold them.\n"
            "Back up kohle.db and export them first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    op.drop_table('rules')
