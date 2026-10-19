"""classification records

One row per imported line: what was proposed, which rule matched, where it
landed, and whether a human has corrected it.

Revision ID: 3e7b91c0af52
Revises: c5b8e2f47a13
Create Date: 2026-09-11 23:55:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3e7b91c0af52'
down_revision: str | Sequence[str] | None = 'c5b8e2f47a13'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'classifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('journal_entry_id', sa.Integer(), nullable=False),
        sa.Column('proposed_account_id', sa.Integer(), nullable=False),
        sa.Column('matched_rule_id', sa.Integer(), nullable=True),
        sa.Column('final_account_id', sa.Integer(), nullable=False),
        sa.Column('corrected', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id']),
        sa.ForeignKeyConstraint(['proposed_account_id'], ['accounts.id']),
        sa.ForeignKeyConstraint(['matched_rule_id'], ['rules.id']),
        sa.ForeignKeyConstraint(['final_account_id'], ['accounts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('journal_entry_id', name='uq_classification_journal_entry'),
    )


def _refuse_if_unrepresentable() -> None:
    """Dropping the table discards every classification decision ever made,
    which is the labelled data the whole feature exists to accumulate and which
    the ledger cannot reconstruct. Count it first and refuse rather than lose it
    quietly."""
    conn = op.get_bind()

    classifications = conn.execute(sa.text("SELECT COUNT(*) FROM classifications")).scalar() or 0

    if classifications:
        raise RuntimeError(
            f"Refusing to downgrade: {classifications} classification record(s) would be "
            "dropped, and the previous schema has nowhere to hold them.\n"
            "Back up kohle.db and export them first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    op.drop_table('classifications')
