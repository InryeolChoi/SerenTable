"""Record operator explanation snapshots without rewriting historical confirmations."""

from alembic import op

revision = "0015_matching_explanations"
down_revision = "0014_mock_refund_attempt"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE dining_table ADD COLUMN explanation jsonb")
    op.execute("ALTER TABLE match_run_member ADD COLUMN explanation jsonb")


def downgrade():
    op.execute("ALTER TABLE match_run_member DROP COLUMN explanation")
    op.execute("ALTER TABLE dining_table DROP COLUMN explanation")
