"""split groups

Adds `split_groups` — the trip/label a split can optionally be tagged
under (design §2.2, §6) — and a nullable `splits.group_id` foreign key
pointing at it.

`op.add_column` with an inline `sa.ForeignKey` does not work on SQLite:
Alembic renders the column and then tries to add the constraint as a
separate `ALTER`, which SQLite has no syntax for. `batch_alter_table`
rebuilds the table and preserves its rows instead (design §10.2).

Revision ID: a1cebfe54f33
Revises: 7e7428c80058
Create Date: 2026-09-14 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1cebfe54f33'
down_revision: str | Sequence[str] | None = '7e7428c80058'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'split_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_split_group_name'),
    )

    with op.batch_alter_table("splits") as batch_op:
        batch_op.add_column(sa.Column('group_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_split_group', 'split_groups', ['group_id'], ['id']
        )


def _refuse_if_unrepresentable() -> None:
    """Dropping `split_groups` loses every trip label; dropping `group_id`
    loses which splits belong to which trip. Count both first and refuse
    rather than lose either quietly."""
    conn = op.get_bind()

    groups = conn.execute(sa.text("SELECT COUNT(*) FROM split_groups")).scalar() or 0
    tagged = conn.execute(
        sa.text("SELECT COUNT(*) FROM splits WHERE group_id IS NOT NULL")
    ).scalar() or 0

    if groups or tagged:
        raise RuntimeError(
            f"Refusing to downgrade: {groups} split group(s) and {tagged} tagged "
            "split(s) would be dropped, and the previous schema has nowhere to hold "
            "them.\n"
            "Back up kohle.db and export them first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    with op.batch_alter_table("splits") as batch_op:
        batch_op.drop_constraint('fk_split_group', type_='foreignkey')
        batch_op.drop_column('group_id')

    op.drop_table('split_groups')
