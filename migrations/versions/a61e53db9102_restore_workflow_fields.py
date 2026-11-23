"""Restore fields used by the original workflows."""

import sqlalchemy as sa
from alembic import op

revision = "a61e53db9102"
down_revision = "5e551f592af0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("phone", sa.String(25)))
    op.add_column("users", sa.Column("created_at", sa.DateTime(timezone=True)))
    with op.batch_alter_table("crops") as batch:
        batch.add_column(sa.Column("notes", sa.Text()))
        batch.alter_column("planted_on", existing_type=sa.Date(), nullable=True)
    op.execute("UPDATE farms SET area = ROUND(area * 2.4710538147, 2) WHERE area IS NOT NULL")


def downgrade():
    op.execute("UPDATE farms SET area = ROUND(area / 2.4710538147, 2) WHERE area IS NOT NULL")
    with op.batch_alter_table("crops") as batch:
        batch.alter_column("planted_on", existing_type=sa.Date(), nullable=False)
        batch.drop_column("notes")
    op.drop_column("users", "created_at")
    op.drop_column("users", "phone")
