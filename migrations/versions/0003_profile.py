"""Participant drafts and purpose/version consent history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_profile"
down_revision = "0002_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "participant_profile",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_user.id"), primary_key=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "consent_record",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("purpose IN ('privacy', 'operation')", name="consent_purpose"),
    )
    op.create_index(
        "consent_record_user_purpose_id", "consent_record", ["user_id", "purpose", "id"]
    )


def downgrade():
    op.drop_table("consent_record")
    op.drop_table("participant_profile")
