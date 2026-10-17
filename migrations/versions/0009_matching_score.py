"""ADR-0011: excluded pairs and recorded scores. Additive only; existing rows stay as they are."""

from alembic import op

revision = "0009_matching_score"
down_revision = "0008_source_preparation"
branch_labels = None
depends_on = None


def upgrade():
    # One row per unordered user pair and source (MAT-05). Filled by later features
    # (block, confirmed report, "do not match again"); matching only reads it.
    op.execute("""CREATE TABLE participant_exclusion (
        user_low uuid NOT NULL REFERENCES app_user(id),
        user_high uuid NOT NULL REFERENCES app_user(id),
        source varchar(24) NOT NULL
            CHECK (source IN ('block', 'confirmed_report', 'avoid')),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY (user_low, user_high, source),
        CHECK (user_low < user_high)
    )""")
    op.execute("ALTER TABLE match_run ADD COLUMN policy jsonb")
    op.execute("ALTER TABLE match_run ADD COLUMN search_complete boolean")
    op.execute("ALTER TABLE dining_table ADD COLUMN score numeric(6, 2)")
    op.execute("ALTER TABLE dining_table ADD COLUMN components jsonb")


def downgrade():
    op.execute("ALTER TABLE dining_table DROP COLUMN components")
    op.execute("ALTER TABLE dining_table DROP COLUMN score")
    op.execute("ALTER TABLE match_run DROP COLUMN search_complete")
    op.execute("ALTER TABLE match_run DROP COLUMN policy")
    op.execute("DROP TABLE participant_exclusion")
