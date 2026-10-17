"""Append-only failure choices, entitlement reservations and mock refund evidence."""

from alembic import op

revision = "0010_match_resolution"
down_revision = "0009_matching_score"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE match_resolution (
        id uuid PRIMARY KEY, application_id uuid NOT NULL, user_id uuid NOT NULL,
        failure_run_id uuid NOT NULL REFERENCES match_run(id), request_key uuid NOT NULL,
        action varchar(16) NOT NULL CHECK (action IN ('TRANSFER','HOLD','REFUND')),
        event_slot_id uuid REFERENCES event_slot(id), previous_state varchar(24) NOT NULL,
        reason_code varchar(48), created_at timestamptz NOT NULL, policy_version varchar(64) NOT
        NULL,
        FOREIGN KEY (application_id,user_id) REFERENCES application(id,user_id),
        UNIQUE (application_id,failure_run_id), UNIQUE (user_id,request_key),
        CHECK ((action='TRANSFER')=(event_slot_id IS NOT NULL)))""")
    op.execute("""ALTER TABLE application_candidate ADD COLUMN source_resolution_id uuid
        REFERENCES match_resolution(id)""")
    op.execute("""CREATE TABLE entitlement_binding (
        id uuid PRIMARY KEY, entitlement_id uuid NOT NULL REFERENCES entitlement(id),
        application_id uuid NOT NULL, user_id uuid NOT NULL,
        request_key uuid, started_at timestamptz NOT NULL, ended_at timestamptz,
        FOREIGN KEY (application_id,user_id) REFERENCES application(id,user_id),
        CHECK (ended_at IS NULL OR ended_at>=started_at), UNIQUE(user_id,request_key))""")
    op.execute("ALTER TABLE entitlement ADD CONSTRAINT entitlement_id_user UNIQUE(id,user_id)")
    op.execute("""ALTER TABLE entitlement_binding ADD CONSTRAINT entitlement_binding_owner
        FOREIGN KEY(entitlement_id,user_id) REFERENCES entitlement(id,user_id)""")
    op.execute("""CREATE UNIQUE INDEX entitlement_binding_live_right ON
    entitlement_binding(entitlement_id)
        WHERE ended_at IS NULL""")
    op.execute("""CREATE UNIQUE INDEX entitlement_binding_live_application ON
    entitlement_binding(application_id)
        WHERE ended_at IS NULL""")
    # Existing grants retain the original reservation; no confirmed result is rewritten.
    op.execute("""INSERT INTO
    entitlement_binding(id,entitlement_id,application_id,user_id,started_at)
        SELECT id,id,application_id,user_id,starts_at FROM entitlement WHERE kind='SINGLE'""")
    op.execute("""CREATE TABLE membership_extension (
        application_id uuid PRIMARY KEY REFERENCES application(id),
        entitlement_id uuid NOT NULL REFERENCES entitlement(id),
        previous_expires_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL, policy_version varchar(64) NOT NULL,
        CHECK (expires_at=previous_expires_at+interval '7 days'))""")
    op.execute("ALTER TABLE payment DROP CONSTRAINT payment_state")
    op.execute("""ALTER TABLE payment ADD CONSTRAINT payment_state
        CHECK (state IN ('PENDING','PAID','FAILED','REFUNDED'))""")
    op.execute("""CREATE TABLE mock_refund_event (
        resolution_id uuid NOT NULL REFERENCES match_resolution(id),
        payment_id uuid NOT NULL REFERENCES payment(id), state varchar(24) NOT NULL,
        amount_krw integer NOT NULL CHECK (amount_krw>=0), created_at timestamptz NOT NULL,
        PRIMARY KEY(payment_id,state), CHECK(state IN
        ('REFUND_REQUESTED','REFUND_PROCESSING','REFUNDED')))""")


def downgrade():
    # Refuse downgrade after refund evidence rather than silently erasing its state.
    op.execute("ALTER TABLE payment DROP CONSTRAINT payment_state")
    op.execute(
        "ALTER TABLE payment ADD CONSTRAINT payment_state "
        "CHECK(state IN ('PENDING','PAID','FAILED'))"
    )
    op.drop_table("mock_refund_event")
    op.drop_table("membership_extension")
    op.drop_table("entitlement_binding")
    op.drop_constraint("entitlement_id_user", "entitlement", type_="unique")
    op.drop_column("application_candidate", "source_resolution_id")
    op.drop_table("match_resolution")
