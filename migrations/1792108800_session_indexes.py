"""Index sessions by charging point and time.

The day, range and KPI queries filter sessions by charging point and a time
window; without these indexes each of them scans the whole table.
"""
from alembic import op

revision = "1792108800"
down_revision = "1792022400"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_sessions_cp_id_start", "sessions", ["cp_id", "start"], if_not_exists=True)
    op.create_index("ix_sessions_cp_id_end", "sessions", ["cp_id", "end"], if_not_exists=True)


def downgrade():
    op.drop_index("ix_sessions_cp_id_end", table_name="sessions", if_exists=True)
    op.drop_index("ix_sessions_cp_id_start", table_name="sessions", if_exists=True)
