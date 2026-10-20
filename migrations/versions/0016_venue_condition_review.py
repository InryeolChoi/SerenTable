"""Track the last verified allocated-venue conditions; historical NULL stays unknown."""

from alembic import op

revision = "0016_venue_condition_review"
down_revision = "0015_matching_explanations"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE venue_allocation ADD COLUMN reviewed_conditions_snapshot text")


def downgrade():
    op.execute("ALTER TABLE venue_allocation DROP COLUMN reviewed_conditions_snapshot")
