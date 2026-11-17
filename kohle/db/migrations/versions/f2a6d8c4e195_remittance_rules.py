"""remittance rules

Adds `rules.unit_id`, the currency of a remittance rule, and the remittance
columns of `classifications`: the counterpart and currency of a line waiting in
the pending bucket, and the entry that completes it. The CHECKs tie each to the
kind it belongs to.

Revision ID: f2a6d8c4e195
Revises: e8b3c5a1d704
Create Date: 2026-11-18 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2a6d8c4e195'
down_revision: str | Sequence[str] | None = 'e8b3c5a1d704'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Batch mode: SQLite cannot add a foreign key or a CHECK to an existing table.
    with op.batch_alter_table('rules') as batch_op:
        batch_op.add_column(sa.Column('unit_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_rule_unit', 'units', ['unit_id'], ['id'])
        batch_op.create_check_constraint('ck_rule_remittance_unit', "(kind = 'remittance') = (unit_id IS NOT NULL)")
    with op.batch_alter_table('classifications') as batch_op:
        batch_op.add_column(sa.Column('remittance_account_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('remittance_unit_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('completion_entry_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_classification_remittance_account', 'accounts', ['remittance_account_id'], ['id']
        )
        batch_op.create_foreign_key('fk_classification_remittance_unit', 'units', ['remittance_unit_id'], ['id'])
        batch_op.create_foreign_key(
            'fk_classification_completion', 'journal_entries', ['completion_entry_id'], ['id']
        )
        batch_op.create_unique_constraint('uq_classification_completion', ['completion_entry_id'])
        batch_op.create_check_constraint(
            'ck_classification_remittance',
            "(kind = 'remittance') = (remittance_account_id IS NOT NULL) "
            "AND (remittance_account_id IS NULL) = (remittance_unit_id IS NULL)",
        )
        batch_op.create_check_constraint(
            'ck_classification_completion', "completion_entry_id IS NULL OR kind = 'remittance'"
        )


def _refuse_if_unrepresentable() -> None:
    """A remittance rule or classification has no meaning in the previous
    schema, where it would read as a category and lose its unit."""
    conn = op.get_bind()
    rules = conn.execute(sa.text("SELECT COUNT(*) FROM rules WHERE unit_id IS NOT NULL")).scalar() or 0
    classifications = (
        conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM classifications WHERE remittance_account_id IS NOT NULL "
                "OR remittance_unit_id IS NOT NULL OR completion_entry_id IS NOT NULL"
            )
        ).scalar()
        or 0
    )

    if rules or classifications:
        raise RuntimeError(
            f"Refusing to downgrade: {rules} rule(s) and {classifications} classification(s) use remittances, "
            "and the previous schema would lose their counterpart and unit.\n"
            "Back up kohle.db and retire or reclassify them first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    with op.batch_alter_table('classifications') as batch_op:
        batch_op.drop_constraint('ck_classification_completion', type_='check')
        batch_op.drop_constraint('ck_classification_remittance', type_='check')
        batch_op.drop_constraint('uq_classification_completion', type_='unique')
        batch_op.drop_constraint('fk_classification_completion', type_='foreignkey')
        batch_op.drop_constraint('fk_classification_remittance_unit', type_='foreignkey')
        batch_op.drop_constraint('fk_classification_remittance_account', type_='foreignkey')
        batch_op.drop_column('completion_entry_id')
        batch_op.drop_column('remittance_unit_id')
        batch_op.drop_column('remittance_account_id')
    with op.batch_alter_table('rules') as batch_op:
        batch_op.drop_constraint('ck_rule_remittance_unit', type_='check')
        batch_op.drop_constraint('fk_rule_unit', type_='foreignkey')
        batch_op.drop_column('unit_id')
