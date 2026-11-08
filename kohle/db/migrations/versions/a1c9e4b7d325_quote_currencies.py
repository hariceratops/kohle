"""quote currencies

Adds `price_bindings.quote_currency` and `prices.currency`, the currency a
binding's closes are quoted in and the currency each stored close is in.
Existing rows come out as EUR, which is what they were treated as.

Revision ID: a1c9e4b7d325
Revises: d7f3b9a1c846
Create Date: 2026-11-08 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c9e4b7d325'
down_revision: str | Sequence[str] | None = 'd7f3b9a1c846'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('price_bindings', sa.Column('quote_currency', sa.String(), nullable=False, server_default='EUR'))
    op.add_column('prices', sa.Column('currency', sa.String(), nullable=False, server_default='EUR'))


def _refuse_if_unrepresentable() -> None:
    """After a downgrade a rupee close would read as euros."""
    conn = op.get_bind()
    bindings = conn.execute(sa.text("SELECT COUNT(*) FROM price_bindings WHERE quote_currency <> 'EUR'")).scalar() or 0
    closes = conn.execute(sa.text("SELECT COUNT(*) FROM prices WHERE currency <> 'EUR'")).scalar() or 0

    if bindings or closes:
        raise RuntimeError(
            f"Refusing to downgrade: {bindings} binding(s) are quoted in a currency other than EUR and "
            f"{closes} stored close(s) are in one; the previous schema would read them as euros.\n"
            "Back up kohle.db and rebind or note them down first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    with op.batch_alter_table('prices') as batch_op:
        batch_op.drop_column('currency')
    with op.batch_alter_table('price_bindings') as batch_op:
        batch_op.drop_column('quote_currency')
