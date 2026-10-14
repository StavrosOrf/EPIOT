"""Create the electricity table on fresh installs (older installs already have it)."""
from alembic import op
from backend.models import PowerMix

revision = "1792022400"
down_revision = "1791936000"
branch_labels = None
depends_on = None


def upgrade():
    PowerMix.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    # Existing installations populated this table before migrations managed it.
    pass
