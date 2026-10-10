"""counterparty on journal entries

Imported entries keep what the bank said about the other side of the movement,
so a classification rule has a payee to match on. Nullable: entries made
through `record` and `record-split` have no counterparty concept.

Revision ID: a1d7c4e9b208
Revises: 7f3c1d9a2b40
Create Date: 2026-09-10 22:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1d7c4e9b208'
down_revision: str | Sequence[str] | None = '7f3c1d9a2b40'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Plain add_column rather than batch_alter_table: nothing here relaxes a
    # constraint or adds a foreign key, which is what forced the table rebuild
    # in the multi-unit migration.
    op.add_column('journal_entries', sa.Column('counterparty_name', sa.String(), nullable=True))
    op.add_column('journal_entries', sa.Column('counterparty_iban', sa.String(), nullable=True))


def _refuse_if_unrepresentable() -> None:
    """The old schema has nowhere to put a counterparty, so dropping the columns
    discards it. Count it first and refuse rather than lose it quietly."""
    conn = op.get_bind()

    populated = conn.execute(sa.text(
        "SELECT COUNT(*) FROM journal_entries "
        "WHERE counterparty_name IS NOT NULL OR counterparty_iban IS NOT NULL"
    )).scalar() or 0

    if populated:
        raise RuntimeError(
            f"Refusing to downgrade: {populated} journal entrie(s) carry a counterparty, "
            "which the previous schema cannot hold.\n"
            "Back up kohle.db and export those entries first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    # SQLite has supported DROP COLUMN since 3.35, so no table rebuild.
    op.drop_column('journal_entries', 'counterparty_iban')
    op.drop_column('journal_entries', 'counterparty_name')
