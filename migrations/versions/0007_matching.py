"""Automatic matching: one run per slot generation, its tables and the matching axis.

See docs/design/matching-contract.md (Work #6 Task ①-a, approved 2026-10-17). Matching is
a separate axis from application and payment state: application.state stays
DRAFT/SUBMITTED/CANCELED and the matching axis lives in match_participation.
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_matching"
down_revision = "0006_payment"
branch_labels = None
depends_on = None

# PRD matching-axis states. ①-b writes CONFIRMED/NO_MATCH/EXCEPTION only; the rest are
# added by ①-c (ALTERNATIVE_OFFERED/TRANSFERRED/REALLOCATING) and stay reserved here so a
# later step never has to rewrite the constraint.
MATCHING_STATES = (
    "WAITING",
    "MATCHING",
    "REALLOCATING",
    "CONFIRMED",
    "ALTERNATIVE_OFFERED",
    "TRANSFERRED",
    "NO_MATCH",
    "EXCEPTION",
)


def upgrade():
    op.create_table(
        "match_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_slot_id", sa.Uuid(), sa.ForeignKey("event_slot.id"), nullable=False),
        # Generation counter for the slot: a rerun after an abandoned generation is a new
        # attempt, and a successful generation ends the slot's matching for good.
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        # Rule and algorithm are recorded so a later scoring rule (U05) can be told apart
        # from these results instead of silently overwriting them.
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("seated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason_code", sa.String(48), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'ABANDONED')", name="match_run_state"
        ),
        sa.CheckConstraint(
            "(state = 'RUNNING') = (finished_at IS NULL)", name="match_run_finished_at"
        ),
        sa.CheckConstraint("attempt > 0", name="match_run_attempt"),
        sa.CheckConstraint("seated_count >= 0", name="match_run_seated_count"),
        sa.UniqueConstraint("event_slot_id", "attempt", name="match_run_slot_attempt"),
    )
    # At most one live generation per slot: two runners cannot both be running it, and the
    # constraint is what settles a concurrent start rather than a check-then-insert race.
    op.create_index(
        "match_run_slot_running",
        "match_run",
        ["event_slot_id"],
        unique=True,
        postgresql_where=sa.text("state = 'RUNNING'"),
    )
    op.create_table(
        "dining_table",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("match_run_id", sa.Uuid(), sa.ForeignKey("match_run.id"), nullable=False),
        sa.Column("event_slot_id", sa.Uuid(), sa.ForeignKey("event_slot.id"), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("member_count BETWEEN 4 AND 6", name="dining_table_member_count"),
        # Target for the assignment composite FK that pins a table to its own slot.
        sa.UniqueConstraint("id", "event_slot_id", name="dining_table_id_slot"),
    )
    op.create_table(
        "match_run_member",
        sa.Column("match_run_id", sa.Uuid(), sa.ForeignKey("match_run.id"), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(48), nullable=True),
        sa.Column("dining_table_id", sa.Uuid(), sa.ForeignKey("dining_table.id"), nullable=True),
        sa.PrimaryKeyConstraint("match_run_id", "application_id"),
        sa.CheckConstraint(
            "outcome IN ('SEATED', 'UNSEATED', 'EXCEPTION')", name="match_run_member_outcome"
        ),
        sa.CheckConstraint(
            "(outcome = 'SEATED') = (dining_table_id IS NOT NULL)",
            name="match_run_member_table",
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "user_id"],
            ["application.id", "application.user_id"],
            name="match_run_member_owner",
        ),
    )
    op.create_index("match_run_member_run", "match_run_member", ["match_run_id"])
    op.create_table(
        "table_assignment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("dining_table_id", sa.Uuid(), nullable=False),
        sa.Column("event_slot_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # Reallocation (①-c) ends the old assignment instead of deleting it; only live rows
        # are unique per application.
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["dining_table_id", "event_slot_id"],
            ["dining_table.id", "dining_table.event_slot_id"],
            name="table_assignment_table_slot",
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "user_id"],
            ["application.id", "application.user_id"],
            name="table_assignment_owner",
        ),
    )
    # U07 계약: 한 신청의 살아 있는 배치 소유권은 최대 하나.
    op.create_index(
        "table_assignment_live_application",
        "table_assignment",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_table(
        "match_participation",
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("application.id"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("event_slot_id", sa.Uuid(), sa.ForeignKey("event_slot.id"), nullable=True),
        sa.Column("dining_table_id", sa.Uuid(), sa.ForeignKey("dining_table.id"), nullable=True),
        sa.Column("match_run_id", sa.Uuid(), sa.ForeignKey("match_run.id"), nullable=True),
        sa.Column("reason_code", sa.String(48), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN (" + ", ".join(f"'{state}'" for state in MATCHING_STATES) + ")",
            name="match_participation_state",
        ),
        # CONFIRMED alone carries a table and slot; a later TRANSFERRED may too, so the
        # constraint is stated in one direction only.
        sa.CheckConstraint(
            "dining_table_id IS NULL OR (state = 'CONFIRMED' AND event_slot_id IS NOT NULL)",
            name="match_participation_table",
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "user_id"],
            ["application.id", "application.user_id"],
            name="match_participation_owner",
        ),
    )
    op.create_index("match_participation_user", "match_participation", ["user_id"])


def downgrade():
    op.drop_table("match_participation")
    op.drop_table("table_assignment")
    op.drop_table("match_run_member")
    op.drop_table("dining_table")
    op.drop_table("match_run")
