import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "worker_heartbeat",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("worker_heartbeat")
