"""entry reversals

Adds `journal_entries.reverses_entry_id`, the link from a reversing entry to the
entry it undoes. The lot replay treats the pair as if neither were recorded.

Revision ID: a9d3c7e1b406
Revises: f2a6d8c4e195
Create Date: 2026-11-18 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a9d3c7e1b406'
down_revision: str | Sequence[str] | None = 'f2a6d8c4e195'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Batch mode: SQLite cannot add a foreign key or a UNIQUE to an existing table.
    with op.batch_alter_table('journal_entries') as batch_op:
        batch_op.add_column(sa.Column('reverses_entry_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_journal_entry_reverses', 'journal_entries', ['reverses_entry_id'], ['id'])
        batch_op.create_unique_constraint('uq_journal_entry_reverses', ['reverses_entry_id'])


def _refuse_if_unrepresentable() -> None:
    """A reversal read as an ordinary entry would book a lot and a gain that
    never happened."""
    conn = op.get_bind()
    reversals = conn.execute(sa.text("SELECT COUNT(*) FROM journal_entries WHERE reverses_entry_id IS NOT NULL")).scalar() or 0

    if reversals:
        raise RuntimeError(
            f"Refusing to downgrade: {reversals} entry(ies) reverse another, and the previous schema "
            "would read them as ordinary entries and book lots and gains that never happened.\n"
            "Back up kohle.db first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    with op.batch_alter_table('journal_entries') as batch_op:
        batch_op.drop_constraint('uq_journal_entry_reverses', type_='unique')
        batch_op.drop_constraint('fk_journal_entry_reverses', type_='foreignkey')
        batch_op.drop_column('reverses_entry_id')
