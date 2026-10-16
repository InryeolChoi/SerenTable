"""Mock payments for applications and the entitlements they grant."""

import sqlalchemy as sa
from alembic import op

revision = "0006_payment"
down_revision = "0005_application"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        # Refund states (U04) are added with the refund work, not here.
        sa.Column("state", sa.String(24), nullable=False),
        # Product snapshot at purchase: later catalog changes never alter this payment.
        sa.Column("product_code", sa.String(32), nullable=False),
        sa.Column("product_name", sa.String(64), nullable=False),
        sa.Column("product_kind", sa.String(16), nullable=False),
        sa.Column("product_version", sa.String(64), nullable=False),
        sa.Column("amount_krw", sa.Integer(), nullable=False),
        sa.Column("period_months", sa.Integer(), nullable=True),
        sa.Column("policy_version", sa.String(64), nullable=False),
        # Mock only: the participant explicitly asked the mock processor to fail.
        sa.Column("simulated_failure", sa.Boolean(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('PENDING', 'PAID', 'FAILED')", name="payment_state"),
        sa.CheckConstraint(
            "(state = 'PENDING') = (completed_at IS NULL)", name="payment_completed_at"
        ),
        sa.CheckConstraint("amount_krw >= 0", name="payment_amount_nonnegative"),
        sa.CheckConstraint(
            "(product_kind = 'SINGLE' AND period_months IS NULL)"
            " OR (product_kind = 'MEMBERSHIP' AND period_months > 0)",
            name="payment_product_period",
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "user_id"],
            ["application.id", "application.user_id"],
            name="payment_application_owner",
        ),
        # A retried identical request resolves to the same payment.
        sa.UniqueConstraint("user_id", "request_key", name="payment_user_request"),
        # Target for the entitlement composite FK that pins its owner to the payer.
        sa.UniqueConstraint("id", "user_id", name="payment_id_user"),
    )
    # At most one in-flight or successful attempt per application; FAILED rows stay as
    # history and do not block a new attempt.
    op.create_index(
        "payment_application_live",
        "payment",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('PENDING', 'PAID')"),
    )
    op.create_table(
        "entitlement",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        # A single pass is held for the application it was bought with.
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "(kind = 'SINGLE' AND expires_at IS NULL AND application_id IS NOT NULL)"
            " OR (kind = 'MEMBERSHIP' AND expires_at > starts_at AND application_id IS NULL)",
            name="entitlement_kind_shape",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id", "user_id"],
            ["payment.id", "payment.user_id"],
            name="entitlement_payment_owner",
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "user_id"],
            ["application.id", "application.user_id"],
            name="entitlement_application_owner",
        ),
        # One payment never grants two entitlements, however often it is retried.
        sa.UniqueConstraint("payment_id", name="entitlement_payment"),
    )
    op.create_index("entitlement_user", "entitlement", ["user_id"])


def downgrade():
    op.drop_table("entitlement")
    op.drop_table("payment")
