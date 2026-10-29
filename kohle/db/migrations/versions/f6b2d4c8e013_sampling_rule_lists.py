"""sampling rule lists

Adds `sampling_rule_lists`, the ledger's net-worth sampling rules, and seeds
the default list into every ledger. The default reproduces the pre-feature
`--period-end last-working-day`.

Revision ID: f6b2d4c8e013
Revises: e5a1c3b7d902
Create Date: 2026-10-29 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f6b2d4c8e013'
down_revision: str | Sequence[str] | None = 'e5a1c3b7d902'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The default rule list, defined here and nowhere else in kohle/: this is its
# only writer, and init gets it by running this migration.
DEFAULT_SAMPLING_RULES = "mid-month: day 15; salary: last workday"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'sampling_rule_lists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rules', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.get_bind().execute(
        sa.text("INSERT INTO sampling_rule_lists (rules) VALUES (:rules)"),
        {"rules": DEFAULT_SAMPLING_RULES},
    )


def _refuse_if_unrepresentable() -> None:
    """The previous schema behaves as the default list does, so only that is
    representable; any other list is a user declaration it cannot hold."""
    conn = op.get_bind()
    rows = [r[0] for r in conn.execute(sa.text("SELECT rules FROM sampling_rule_lists ORDER BY id"))]

    if rows != [DEFAULT_SAMPLING_RULES]:
        raise RuntimeError(
            "Refusing to downgrade: the sampling rules are not the default list, and the "
            "previous schema has nowhere to hold them.\n"
            "Back up kohle.db and note them down first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()
    op.drop_table('sampling_rule_lists')
