"""Append mock refund failure and retry evidence without rewriting past refunds."""

from alembic import op

revision = "0014_mock_refund_attempt"
down_revision = "0013_operator_audit"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE mock_refund_attempt (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        resolution_id uuid NOT NULL REFERENCES match_resolution(id),
        request_key uuid NOT NULL,
        operator_id uuid REFERENCES app_user(id),
        payment_id uuid NOT NULL REFERENCES payment(id),
        amount_krw integer NOT NULL CHECK(amount_krw>=0),
        attempt_number integer NOT NULL CHECK(attempt_number>0),
        state varchar(16) NOT NULL CHECK(state IN ('FAILED','SUCCEEDED')),
        error_code varchar(48), created_at timestamptz NOT NULL,
        UNIQUE(resolution_id,request_key), UNIQUE(operator_id,request_key),
        UNIQUE(resolution_id,attempt_number),
        CHECK ((state='FAILED')=(error_code IS NOT NULL)))""")


def downgrade():
    op.drop_table("mock_refund_attempt")
