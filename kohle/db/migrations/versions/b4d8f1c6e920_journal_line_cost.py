"""journal line cost

Adds `journal_lines.cost`, the whole value of a line when it was stated
rather than derived from quantity and price. Existing rows stay NULL, which
reads as quantity times price, exactly as before.

Revision ID: b4d8f1c6e920
Revises: a1c9e4b7d325
Create Date: 2026-11-08 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b4d8f1c6e920'
down_revision: str | Sequence[str] | None = 'a1c9e4b7d325'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('journal_lines', sa.Column('cost', sa.Numeric(20, 8), nullable=True))


def _refuse_if_unrepresentable() -> None:
    """After a downgrade a stated total would be re-derived from a rounded price."""
    stated = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM journal_lines WHERE cost IS NOT NULL")).scalar() or 0

    if stated:
        raise RuntimeError(
            f"Refusing to downgrade: {stated} journal line(s) carry a stated total; the previous schema "
            "would recompute their value from a rounded unit price and the entries would no longer balance.\n"
            "Back up kohle.db and note them down first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    with op.batch_alter_table('journal_lines') as batch_op:
        batch_op.drop_column('cost')
