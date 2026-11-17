"""transfer rules

Adds `rules.kind` and `classifications.kind`, each defaulting to 'category' so
every existing row reads as before, and `classifications.mirror_of_entry_id`,
the transfer a line was absorbed into, with a CHECK tying it to the 'mirror'
kind and a UNIQUE so a transfer has at most one mirror.

Revision ID: e8b3c5a1d704
Revises: c7e2a9d4b185
Create Date: 2026-11-17 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e8b3c5a1d704'
down_revision: str | Sequence[str] | None = 'c7e2a9d4b185'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RULE_KIND = sa.Enum('category', 'transfer', 'remittance', name='rulekind')
CLASSIFICATION_KIND = sa.Enum('category', 'transfer', 'mirror', 'remittance', name='classificationkind')


def upgrade() -> None:
    """Upgrade schema."""
    # Batch mode: SQLite cannot add a foreign key or a CHECK to an existing table.
    with op.batch_alter_table('rules') as batch_op:
        batch_op.add_column(sa.Column('kind', RULE_KIND, nullable=False, server_default='category'))
    with op.batch_alter_table('classifications') as batch_op:
        batch_op.add_column(sa.Column('kind', CLASSIFICATION_KIND, nullable=False, server_default='category'))
        batch_op.add_column(sa.Column('mirror_of_entry_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_classification_mirror_of', 'journal_entries', ['mirror_of_entry_id'], ['id']
        )
        batch_op.create_unique_constraint('uq_classification_mirror_of', ['mirror_of_entry_id'])
        batch_op.create_check_constraint(
            'ck_classification_mirror', "(kind = 'mirror') = (mirror_of_entry_id IS NOT NULL)"
        )


def _refuse_if_unrepresentable() -> None:
    """A transfer rule or classification has no meaning in the previous schema,
    where it would silently read as a category."""
    conn = op.get_bind()
    rules = conn.execute(sa.text("SELECT COUNT(*) FROM rules WHERE kind != 'category'")).scalar() or 0
    classifications = (
        conn.execute(
            sa.text("SELECT COUNT(*) FROM classifications WHERE kind != 'category' OR mirror_of_entry_id IS NOT NULL")
        ).scalar()
        or 0
    )

    if rules or classifications:
        raise RuntimeError(
            f"Refusing to downgrade: {rules} rule(s) and {classifications} classification(s) use transfers, "
            "and the previous schema would read them as categories.\n"
            "Back up kohle.db and retire or reclassify them first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    with op.batch_alter_table('classifications') as batch_op:
        batch_op.drop_constraint('ck_classification_mirror', type_='check')
        batch_op.drop_constraint('uq_classification_mirror_of', type_='unique')
        batch_op.drop_constraint('fk_classification_mirror_of', type_='foreignkey')
        batch_op.drop_column('mirror_of_entry_id')
        batch_op.drop_column('kind')
    with op.batch_alter_table('rules') as batch_op:
        batch_op.drop_column('kind')
