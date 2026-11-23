"""Add irrigation records and crop check reminders."""

import sqlalchemy as sa
from alembic import op

revision = "b87fe3449bc1"
down_revision = "a61e53db9102"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "irrigation_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("crop_id", sa.Integer(), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("applied_on", sa.Date(), nullable=False),
        sa.Column("litres", sa.Numeric(14, 3), nullable=False),
        sa.CheckConstraint("litres > 0", name="positive_irrigation_volume"),
    )
    op.create_index("ix_irrigation_entries_crop_id", "irrigation_entries", ["crop_id"])
    op.create_table(
        "crop_checks",
        sa.Column("crop_id", sa.Integer(), sa.ForeignKey("crops.id"), primary_key=True),
        sa.Column("checked_on", sa.Date(), nullable=False),
    )
    op.create_table(
        "irrigation_plans",
        sa.Column("crop_id", sa.Integer(), sa.ForeignKey("crops.id"), primary_key=True),
        sa.Column("acres", sa.Numeric(9, 3), nullable=False),
        sa.Column("efficiency", sa.Integer(), nullable=False),
        sa.CheckConstraint("acres > 0", name="positive_irrigated_area"),
        sa.CheckConstraint("efficiency BETWEEN 30 AND 100", name="valid_irrigation_efficiency"),
    )


def downgrade():
    op.drop_table("irrigation_plans")
    op.drop_table("crop_checks")
    op.drop_index("ix_irrigation_entries_crop_id", table_name="irrigation_entries")
    op.drop_table("irrigation_entries")
