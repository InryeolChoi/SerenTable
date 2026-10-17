"""Private preparation batches, deliberately unrelated to app identities/payments."""

from alembic import op

revision = "0008_source_preparation"
down_revision = "0007_matching"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA source_private")
    op.execute("REVOKE ALL ON SCHEMA source_private FROM PUBLIC")
    op.execute("""CREATE TABLE source_private.import_batch (
        id uuid PRIMARY KEY,
        source_sha256 varchar(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
        rules_version varchar(64) NOT NULL,
        response_count integer NOT NULL CHECK (response_count > 0),
        imported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE (source_sha256, rules_version)
    )""")
    op.execute("""CREATE TABLE source_private.response_staging (
        batch_id uuid NOT NULL REFERENCES source_private.import_batch(id),
        sheet_name varchar(100) NOT NULL,
        source_row_number integer NOT NULL CHECK (source_row_number > 2),
        normalized_data jsonb NOT NULL CHECK (jsonb_typeof(normalized_data) = 'object'),
        review_codes jsonb NOT NULL CHECK (jsonb_typeof(review_codes) = 'array'),
        PRIMARY KEY (batch_id, sheet_name, source_row_number)
    )""")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA source_private FROM PUBLIC")


def downgrade():
    op.execute("DROP TABLE source_private.response_staging")
    op.execute("DROP TABLE source_private.import_batch")
    op.execute("DROP SCHEMA source_private")
