"""Separate CPFT forecasts from observed charging sessions.

Revision ID: 1791849600
Revises: 1729161651
"""

from alembic import op
import sqlalchemy as sa

revision = "1791849600"
down_revision = "1729161651"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "forecast_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
    )
    op.create_table(
        "forecast_hourly",
        sa.Column("run_id", sa.String(), sa.ForeignKey("forecast_runs.id"), primary_key=True),
        sa.Column("cp_id", sa.Integer(), sa.ForeignKey("charging_points.id"), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), primary_key=True),
        sa.Column("occupancy_probability", sa.Float(), nullable=False),
        sa.Column("occupied", sa.Boolean(), nullable=False),
        sa.Column("energy_kwh", sa.Float(), nullable=False),
    )
    op.create_table(
        "forecast_sessions",
        sa.Column("run_id", sa.String(), sa.ForeignKey("forecast_runs.id"), primary_key=True),
        sa.Column("cp_id", sa.Integer(), sa.ForeignKey("charging_points.id"), primary_key=True),
        sa.Column("session_index", sa.Integer(), primary_key=True),
        sa.Column("start", sa.DateTime(), nullable=False),
        sa.Column("end", sa.DateTime(), nullable=False),
        sa.Column("energy_kwh", sa.Float(), nullable=False),
        sa.Column("start_censored", sa.Boolean(), nullable=False),
        sa.Column("end_censored", sa.Boolean(), nullable=False),
    )


def downgrade():
    op.drop_table("forecast_sessions")
    op.drop_table("forecast_hourly")
    op.drop_table("forecast_runs")
