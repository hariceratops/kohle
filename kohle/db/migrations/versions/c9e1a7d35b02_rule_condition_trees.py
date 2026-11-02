"""rule condition trees

A rule's single `pattern` becomes a `condition`: the canonical TOML inline
table of its `when`. Every existing rule becomes `{ any_field = <pattern> }`
with the same id, so `classifications.matched_rule_id` keeps pointing at the
rule that matched. Adds the free-text `note`.

Revision ID: c9e1a7d35b02
Revises: b8d4f0a6c235
Create Date: 2026-11-01 10:00:00.000000

"""
import tomllib
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9e1a7d35b02'
down_revision: str | Sequence[str] | None = 'b8d4f0a6c235'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _toml_string(s: str) -> str:
    """A copy of the application's quoting rule: migrations import no
    application code. A copy that later drifts still parses to the same text."""
    plain = not any((ord(c) < 0x20 and c != "\t") or ord(c) == 0x7F for c in s)
    if plain and '"' not in s and "\\" not in s:
        return f'"{s}"'
    if plain and "'" not in s:
        return f"'{s}'"
    escapes = {"\\": "\\\\", '"': '\\"', "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}
    out = []
    for c in s:
        if c in escapes:
            out.append(escapes[c])
        elif ord(c) < 0x20 or ord(c) == 0x7F:
            out.append(f"\\u{ord(c):04X}")
        else:
            out.append(c)
    return '"' + "".join(out) + '"'


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('rules', sa.Column('condition', sa.String(), nullable=True))
    op.add_column('rules', sa.Column('note', sa.String(), nullable=True))

    conn = op.get_bind()
    # Retired rules too: their text is what keeps a past classification
    # interpretable.
    for rule_id, pattern in conn.execute(sa.text("SELECT id, pattern FROM rules")).fetchall():
        conn.execute(
            sa.text("UPDATE rules SET condition = :condition WHERE id = :id"),
            {"condition": "{ any_field = " + _toml_string(pattern) + " }", "id": rule_id},
        )

    # Batch mode: SQLite cannot tighten or drop a column in place.
    with op.batch_alter_table('rules') as batch_op:
        batch_op.alter_column('condition', existing_type=sa.String(), nullable=False)
        batch_op.drop_column('pattern')


def _refuse_if_unrepresentable() -> None:
    """The previous schema holds one pattern per rule and no notes."""
    conn = op.get_bind()
    unrepresentable = 0
    for condition, note in conn.execute(sa.text("SELECT condition, note FROM rules")).fetchall():
        when = tomllib.loads("when = " + condition)["when"]
        if note is not None or set(when) != {"any_field"}:
            unrepresentable += 1

    if unrepresentable:
        raise RuntimeError(
            f"Refusing to downgrade: {unrepresentable} classification rule(s) use conditions or "
            "notes the previous schema cannot hold.\n"
            "Back up kohle.db and note them down first if you really mean to."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_if_unrepresentable()

    op.add_column('rules', sa.Column('pattern', sa.String(), nullable=True))
    conn = op.get_bind()
    for rule_id, condition in conn.execute(sa.text("SELECT id, condition FROM rules")).fetchall():
        pattern = tomllib.loads("when = " + condition)["when"]["any_field"]
        conn.execute(sa.text("UPDATE rules SET pattern = :pattern WHERE id = :id"), {"pattern": pattern, "id": rule_id})

    with op.batch_alter_table('rules') as batch_op:
        batch_op.alter_column('pattern', existing_type=sa.String(), nullable=False)
        batch_op.drop_column('condition')
        batch_op.drop_column('note')
