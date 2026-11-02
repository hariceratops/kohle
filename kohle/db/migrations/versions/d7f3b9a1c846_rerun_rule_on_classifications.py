"""rerun rule on classifications

Adds `classifications.rerun_rule_id`, the rule a classify-rules run moved a
line with, and a CHECK that at most one of it and `matched_rule_id` is set.
Existing rows come out with no rerun rule.

Revision ID: d7f3b9a1c846
Revises: c9e1a7d35b02
Create Date: 2026-11-01 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd7f3b9a1c846'
down_revision: str | Sequence[str] | None = 'c9e1a7d35b02'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Batch mode: SQLite cannot add a foreign key or a CHECK to an existing table.
    with op.batch_alter_table('classifications') as batch_op:
        batch_op.add_column(sa.Column('rerun_rule_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_classification_rerun_rule', 'rules', ['rerun_rule_id'], ['id'])
        batch_op.create_check_constraint(
            'ck_classification_one_rule', 'matched_rule_id IS NULL OR rerun_rule_id IS NULL'
        )


def _refuse_if_unrepresentable() -> None:
    """A rerun rule is labelled data the ledger cannot rebuild."""
    conn = op.get_bind()
    moved = conn.execute(sa.text("SELECT COUNT(*) FROM classifications WHERE rerun_rule_id IS NOT NULL")).scalar() or 0

    if moved:
        raise RuntimeError(
            f"Refusing to downgrade: {moved} classification(s) were moved by classify-rules, and the "
            "previous schema has nowhere to record the rule.\n"
            "Back up kohle.db and note them down first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    with op.batch_alter_table('classifications') as batch_op:
        batch_op.drop_constraint('ck_classification_one_rule', type_='check')
        batch_op.drop_constraint('fk_classification_rerun_rule', type_='foreignkey')
        batch_op.drop_column('rerun_rule_id')
