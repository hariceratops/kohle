"""people root account

Seeds the `People` root account: a sibling of the existing top-level
financial accounts, never a child of any of them, so a person's balance
never folds into a financial account's rollup (design §2.1, §3.1). No new
`AccountType`/`AccountKind`, no new column — the account tree itself is the
membership marker.

Revision ID: d4a2e6f0b917
Revises: 3e7b91c0af52
Create Date: 2026-09-12 10:00:00.000000

"""
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4a2e6f0b917'
down_revision: str | Sequence[str] | None = '3e7b91c0af52'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PEOPLE_ROOT = "People"


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # uq_account_name is global, so an install that already has an account
    # called "People" would abort mid-migration with a raw UNIQUE constraint
    # failure. Check first and name the collision instead.
    existing = conn.execute(
        sa.text("SELECT id FROM accounts WHERE name = :name"), {"name": PEOPLE_ROOT}
    ).first()
    if existing is not None:
        raise RuntimeError(
            f"Refusing to seed the {PEOPLE_ROOT!r} root: an account named {PEOPLE_ROOT!r} "
            f"already exists (id {existing[0]}). Rename it first if you want the People "
            "branch this migration adds."
        )

    conn.execute(
        sa.text(
            "INSERT INTO accounts (name, type, iban, parent_id, created_at) "
            "VALUES (:name, :type, NULL, NULL, :created_at)"
        ),
        {"name": PEOPLE_ROOT, "type": "asset", "created_at": datetime.now(UTC).replace(tzinfo=None)},
    )


def _refuse_if_unrepresentable() -> None:
    """Deleting a People root that has person accounts under it would orphan
    them, and those accounts hold real balances. Count children and lines
    first and refuse rather than lose either quietly."""
    conn = op.get_bind()

    people_id = conn.execute(
        sa.text("SELECT id FROM accounts WHERE name = :name"), {"name": PEOPLE_ROOT}
    ).scalar()
    if people_id is None:
        return

    children = conn.execute(
        sa.text("SELECT COUNT(*) FROM accounts WHERE parent_id = :parent_id"),
        {"parent_id": people_id},
    ).scalar() or 0
    lines = conn.execute(
        sa.text("SELECT COUNT(*) FROM journal_lines WHERE account_id = :account_id"),
        {"account_id": people_id},
    ).scalar() or 0

    if children or lines:
        raise RuntimeError(
            f"Refusing to downgrade: the {PEOPLE_ROOT!r} root has {children} child "
            f"account(s) and {lines} journal line(s), and the previous schema has "
            "nowhere to hold them.\n"
            "Back up kohle.db and remove them first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    op.execute(sa.text("DELETE FROM accounts WHERE name = :name").bindparams(name=PEOPLE_ROOT))
