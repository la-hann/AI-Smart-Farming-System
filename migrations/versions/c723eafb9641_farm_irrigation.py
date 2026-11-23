"""Allow irrigation records for a whole farm."""

from alembic import op
import sqlalchemy as sa

revision = "c723eafb9641"
down_revision = "b87fe3449bc1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("irrigation_entries", sa.Column("farm_id", sa.Integer()))
    op.execute("""
        UPDATE irrigation_entries SET farm_id = (
            SELECT crops.farm_id FROM crops WHERE crops.id = irrigation_entries.crop_id
        )
    """)
    with op.batch_alter_table(
        "irrigation_entries", naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    ) as batch:
        batch.drop_constraint("fk_irrigation_entries_crop_id_crops", type_="foreignkey")
        batch.alter_column("crop_id", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("farm_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key("fk_irrigation_farm", "farms", ["farm_id"], ["id"])
        batch.create_foreign_key("irrigation_crop_farm", "crops", ["crop_id", "farm_id"], ["id", "farm_id"])
        batch.create_index("ix_irrigation_entries_farm_id", ["farm_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM irrigation_entries WHERE crop_id IS NULL LIMIT 1")).first():
        raise RuntimeError("Assign all whole-farm irrigation records to a crop before downgrading.")
    with op.batch_alter_table("irrigation_entries") as batch:
        batch.drop_index("ix_irrigation_entries_farm_id")
        batch.drop_constraint("irrigation_crop_farm", type_="foreignkey")
        batch.drop_constraint("fk_irrigation_farm", type_="foreignkey")
        batch.alter_column("crop_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key("fk_irrigation_entries_crop_id_crops", "crops", ["crop_id"], ["id"])
        batch.drop_column("farm_id")
