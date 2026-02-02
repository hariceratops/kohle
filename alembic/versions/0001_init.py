from alembic import op
import sqlalchemy

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "debit_categories",
        sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
        sqlalchemy.Column("category", sqlalchemy.String, nullable=False, unique=True)
    )


def downgrade():
    op.drop_table("debit_categories")
