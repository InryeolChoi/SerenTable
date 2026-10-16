"""Participant applications with explicitly chosen slot candidates."""

import sqlalchemy as sa
from alembic import op

revision = "0005_application"
down_revision = "0004_event_slot"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "application",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        # Consent records actually relied on at submission (append-only history rows).
        sa.Column(
            "privacy_consent_id",
            sa.BigInteger(),
            sa.ForeignKey("consent_record.id"),
            nullable=True,
        ),
        sa.Column(
            "operation_consent_id",
            sa.BigInteger(),
            sa.ForeignKey("consent_record.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('DRAFT', 'SUBMITTED', 'CANCELED')", name="application_state"),
        sa.CheckConstraint(
            "state = 'DRAFT' OR (submitted_at IS NOT NULL"
            " AND privacy_consent_id IS NOT NULL AND operation_consent_id IS NOT NULL)",
            name="application_submitted_evidence",
        ),
        sa.CheckConstraint(
            "(state = 'CANCELED') = (canceled_at IS NOT NULL)", name="application_canceled_at"
        ),
        # A resubmitted identical request resolves to the same application.
        sa.UniqueConstraint("user_id", "request_key", name="application_user_request"),
        # Target for the candidate composite FK that pins candidate owner to application owner.
        sa.UniqueConstraint("id", "user_id", name="application_id_user"),
    )
    op.create_table(
        "application_candidate",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_slot_id", sa.Uuid(), sa.ForeignKey("event_slot.id"), nullable=False),
        # Cleared in the same transaction that cancels the application.
        sa.Column("live", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("application_id", "event_slot_id"),
        sa.ForeignKeyConstraint(
            ["application_id", "user_id"],
            ["application.id", "application.user_id"],
            name="application_candidate_owner",
        ),
    )
    # One participant holds a slot in at most one live application (duplicate rule).
    op.create_index(
        "application_candidate_live_user_slot",
        "application_candidate",
        ["user_id", "event_slot_id"],
        unique=True,
        postgresql_where=sa.text("live"),
    )
    op.create_index("application_candidate_slot", "application_candidate", ["event_slot_id"])


def downgrade():
    op.drop_table("application_candidate")
    op.drop_table("application")
