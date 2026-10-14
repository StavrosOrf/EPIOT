"""Tag charger rows with their open-data source and index the spatial joins.

Untagged rows are the Amsterdam pilot chargers. The indexes keep /within fast
once national datasets add hundreds of thousands of charging points.

Revision ID: 1791936000
Revises: 1791849600
"""

from alembic import op
import sqlalchemy as sa

revision = "1791936000"
down_revision = "1791849600"
branch_labels = None
depends_on = None

TAGGED = ("locations", "columns", "charging_points")


def upgrade():
    for table in TAGGED:
        op.add_column(table, sa.Column("source", sa.String(), nullable=True))
        op.add_column(table, sa.Column("external_id", sa.String(), nullable=True))
        op.create_index(f"ix_{table}_source_external_id", table, ["source", "external_id"], unique=True)
    op.create_index("ix_locations_latitude_longitude", "locations", ["latitude", "longitude"])
    op.create_index("ix_columns_location_id", "columns", ["location_id"])
    op.create_index("ix_charging_points_column_id", "charging_points", ["column_id"])


def downgrade():
    op.drop_index("ix_charging_points_column_id", "charging_points")
    op.drop_index("ix_columns_location_id", "columns")
    op.drop_index("ix_locations_latitude_longitude", "locations")
    for table in TAGGED:
        op.drop_index(f"ix_{table}_source_external_id", table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("external_id")
            batch.drop_column("source")
