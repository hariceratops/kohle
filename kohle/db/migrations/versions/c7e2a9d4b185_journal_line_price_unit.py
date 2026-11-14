"""journal line price unit

Adds `journal_lines.price_unit_id`, the currency a line's price and stated
total are in. NULL is the base currency, which every existing row is. A line
priced in another currency has no euro figure of its own: it is derived from
that currency's lots when the ledger is read.

`op.add_column` with an inline `sa.ForeignKey` raises on SQLite after the
column has already been added, so the column goes in through batch mode.

Revision ID: c7e2a9d4b185
Revises: b4d8f1c6e920
Create Date: 2026-11-08 21:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7e2a9d4b185'
down_revision: str | Sequence[str] | None = 'b4d8f1c6e920'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = 'fk_journal_lines_price_unit_id_units'


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('journal_lines') as batch_op:
        batch_op.add_column(sa.Column('price_unit_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(FK_NAME, 'units', ['price_unit_id'], ['id'])


def _refuse_if_unrepresentable() -> None:
    """After a downgrade a line priced in a currency would read as euros."""
    priced = (
        op.get_bind().execute(sa.text("SELECT COUNT(*) FROM journal_lines WHERE price_unit_id IS NOT NULL")).scalar()
        or 0
    )

    if priced:
        raise RuntimeError(
            f"Refusing to downgrade: {priced} journal line(s) are priced in a currency other than the base; "
            "the previous schema would read their figures as euros.\n"
            "Back up kohle.db and note them down first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    with op.batch_alter_table('journal_lines') as batch_op:
        batch_op.drop_constraint(FK_NAME, type_='foreignkey')
        batch_op.drop_column('price_unit_id')
