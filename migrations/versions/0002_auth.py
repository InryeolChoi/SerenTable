"""Synthetic accounts and revocable authentication sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0002_auth"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_user",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("login_id", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("role IN ('participant', 'operator')", name="app_user_role"),
    )
    op.create_table(
        "auth_session",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("auth_session_user_id", "auth_session", ["user_id"])
    op.create_index("auth_session_expires_at", "auth_session", ["expires_at"])
    op.create_table(
        "auth_login_limit",
        sa.Column("login_key", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("window_started", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("auth_login_limit")
    op.drop_table("auth_session")
    op.drop_table("app_user")
