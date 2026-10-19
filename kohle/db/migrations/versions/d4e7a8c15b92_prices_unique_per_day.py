"""prices unique per day

`prices` uniqueness moves from (unit_id, price_date, source) to
(unit_id, price_date): one close per unit per day, whatever the source
(design §4.3). `source` stays and holds the plugin name.

Revision ID: d4e7a8c15b92
Revises: b3f9d2a41c70
Create Date: 2026-10-11 20:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e7a8c15b92'
down_revision: str | Sequence[str] | None = 'b3f9d2a41c70'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('prices') as batch:
        batch.drop_constraint('uq_price_unit_date_source', type_='unique')
        batch.create_unique_constraint('uq_price_unit_date', ['unit_id', 'price_date'])


def downgrade() -> None:
    """Downgrade schema. Lossless: any rows unique per day are unique per source too."""
    with op.batch_alter_table('prices') as batch:
        batch.drop_constraint('uq_price_unit_date', type_='unique')
        batch.create_unique_constraint('uq_price_unit_date_source', ['unit_id', 'price_date', 'source'])
