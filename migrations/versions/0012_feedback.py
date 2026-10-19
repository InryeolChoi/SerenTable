"""Attendance, private feedback and preferences, safety reports and sanctions (ADR-0014)."""

from alembic import op

revision = "0012_feedback"
down_revision = "0011_gathering"
branch_labels = None
depends_on = None

RATING = "smallint NOT NULL CHECK({0} BETWEEN 1 AND 5)"


def upgrade():
    op.execute("""CREATE TABLE attendance_check_in(
        dining_table_id uuid NOT NULL REFERENCES dining_table(id),
        user_id uuid NOT NULL REFERENCES app_user(id),
        checked_in_at timestamptz NOT NULL,
        PRIMARY KEY(dining_table_id, user_id))""")
    op.execute("""CREATE TABLE no_show_review(
        dining_table_id uuid NOT NULL REFERENCES dining_table(id),
        user_id uuid NOT NULL REFERENCES app_user(id),
        decision varchar(24) NOT NULL CHECK(decision IN ('CONFIRMED_NO_SHOW','EXCUSED')),
        reviewed_by uuid NOT NULL REFERENCES app_user(id),
        reviewed_at timestamptz NOT NULL,
        PRIMARY KEY(dining_table_id, user_id))""")
    ratings = ",\n        ".join(
        f"{name} {RATING.format(name)}"
        for name in (
            "table_rating",
            "conversation_rating",
            "venue_rating",
            "rejoin_intent",
            "recommend_intent",
        )
    )
    op.execute(f"""CREATE TABLE table_feedback(
        dining_table_id uuid NOT NULL REFERENCES dining_table(id),
        user_id uuid NOT NULL REFERENCES app_user(id),
        {ratings},
        submitted_at timestamptz NOT NULL,
        PRIMARY KEY(dining_table_id, user_id))""")
    op.execute("""CREATE TABLE person_preference(
        dining_table_id uuid NOT NULL REFERENCES dining_table(id),
        rater_id uuid NOT NULL REFERENCES app_user(id),
        target_id uuid NOT NULL REFERENCES app_user(id),
        choice varchar(16) NOT NULL CHECK(choice IN ('MEET_AGAIN','AVOID')),
        updated_at timestamptz NOT NULL,
        PRIMARY KEY(dining_table_id, rater_id, target_id),
        CHECK(rater_id <> target_id))""")
    op.execute("""CREATE TABLE safety_report(id uuid PRIMARY KEY,
        reporter_id uuid NOT NULL REFERENCES app_user(id),
        reported_id uuid NOT NULL REFERENCES app_user(id),
        dining_table_id uuid REFERENCES dining_table(id),
        reason_code varchar(32) NOT NULL,
        detail text CHECK(detail IS NULL OR length(detail) <= 1000),
        state varchar(16) NOT NULL DEFAULT 'OPEN'
            CHECK(state IN ('OPEN','CONFIRMED','DISMISSED')),
        reviewed_by uuid REFERENCES app_user(id), reviewed_at timestamptz,
        created_at timestamptz NOT NULL,
        CHECK(reporter_id <> reported_id),
        CHECK((state = 'OPEN') = (reviewed_at IS NULL)))""")
    op.execute("""CREATE TABLE participant_sanction(id uuid PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES app_user(id),
        kind varchar(16) NOT NULL CHECK(kind IN ('WARNING','SUSPENSION','PERMANENT_BAN')),
        report_id uuid REFERENCES safety_report(id),
        ends_at timestamptz,
        created_by uuid NOT NULL REFERENCES app_user(id),
        created_at timestamptz NOT NULL,
        CHECK((kind = 'SUSPENSION') = (ends_at IS NOT NULL)))""")
    op.execute(
        "ALTER TABLE participant_exclusion DROP CONSTRAINT participant_exclusion_source_check"
    )
    op.execute("""ALTER TABLE participant_exclusion ADD CONSTRAINT
        participant_exclusion_source_check
        CHECK (source IN ('block', 'confirmed_report', 'avoid', 'report'))""")


def downgrade():
    op.execute("DELETE FROM participant_exclusion WHERE source = 'report'")
    op.execute(
        "ALTER TABLE participant_exclusion DROP CONSTRAINT participant_exclusion_source_check"
    )
    op.execute("""ALTER TABLE participant_exclusion ADD CONSTRAINT
        participant_exclusion_source_check
        CHECK (source IN ('block', 'confirmed_report', 'avoid'))""")
    for name in (
        "participant_sanction",
        "safety_report",
        "person_preference",
        "table_feedback",
        "no_show_review",
        "attendance_check_in",
    ):
        op.drop_table(name)
