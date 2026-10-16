"""Fixed Seoul regions and operator-defined recruitment slots."""

import sqlalchemy as sa
from alembic import op

revision = "0004_event_slot"
down_revision = "0003_profile"
branch_labels = None
depends_on = None

# Official FAQ Q9 (2026-10-16): four Seoul regions; other regions are not approved.
REGIONS = [
    ("hongdae", "홍대", 1),
    ("jamsil", "잠실", 2),
    ("gangnam", "강남", 3),
    ("euljiro", "을지로", 4),
]


def upgrade():
    region = op.create_table(
        "region",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(32), nullable=False, unique=True),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, unique=True),
    )
    op.bulk_insert(
        region, [{"code": code, "name": name, "sort_order": order} for code, name, order in REGIONS]
    )
    op.create_table(
        "event_slot",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("region_code", sa.String(32), sa.ForeignKey("region.code"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("matches_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("starts_at < ends_at", name="event_slot_starts_before_ends"),
        sa.CheckConstraint(
            "closes_at <= matches_at AND matches_at <= starts_at", name="event_slot_time_order"
        ),
        sa.CheckConstraint("capacity BETWEEN 4 AND 100", name="event_slot_capacity"),
        sa.UniqueConstraint("region_code", "starts_at", name="event_slot_region_start"),
    )
    op.create_index("event_slot_closes_at", "event_slot", ["closes_at"])


def downgrade():
    op.drop_table("event_slot")
    op.drop_table("region")
