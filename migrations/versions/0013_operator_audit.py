"""Operator audit trail and exception resolution notes (Work #9, PRD §16)."""

from alembic import op

revision = "0013_operator_audit"
down_revision = "0012_feedback"
branch_labels = None
depends_on = None


def upgrade():
    # Append-only: who changed what, when, why and with what result. No contact data.
    op.execute("""CREATE TABLE operator_audit(id bigserial PRIMARY KEY,
        actor_id uuid REFERENCES app_user(id),
        action varchar(64) NOT NULL,
        target_type varchar(32) NOT NULL,
        target_id text NOT NULL,
        reason text CHECK(reason IS NULL OR length(reason) <= 500),
        before_state jsonb, after_state jsonb,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp())""")
    op.execute("CREATE INDEX operator_audit_recent ON operator_audit(created_at DESC, id DESC)")
    op.execute("CREATE INDEX operator_audit_target ON operator_audit(target_type, target_id)")
    op.execute("ALTER TABLE gathering_exception ADD COLUMN resolution_note text")
    op.execute(
        "ALTER TABLE gathering_exception ADD COLUMN resolved_by uuid REFERENCES app_user(id)"
    )


def downgrade():
    op.execute("ALTER TABLE gathering_exception DROP COLUMN resolved_by")
    op.execute("ALTER TABLE gathering_exception DROP COLUMN resolution_note")
    op.drop_table("operator_audit")
