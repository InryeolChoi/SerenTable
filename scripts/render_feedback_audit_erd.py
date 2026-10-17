"""Render the reviewed 0012/0013 physical schema summary as a standalone SVG.

Full cardinalities and FK roles: docs/design/erd/feedback-audit-physical.mmd.
"""

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = [
    ("attendance_check_in", "PK/FK table + user", "checked_in_at"),
    ("no_show_review", "PK/FK table + user; FK reviewed_by", "CONFIRMED_NO_SHOW / EXCUSED"),
    ("table_feedback", "PK/FK table + user", "5 ratings (1..5), submitted_at"),
    ("person_preference", "PK/FK table + rater + target", "MEET_AGAIN / AVOID; rater != target"),
    ("safety_report", "PK id; FK reporter, reported, table?", "OPEN / CONFIRMED / DISMISSED"),
    (
        "participant_sanction",
        "PK id; FK user, report?, created_by",
        "WARNING / SUSPENSION / PERMANENT_BAN",
    ),
    ("operator_audit", "PK bigint id; FK actor?", "action, target, reason, before/after, time"),
    (
        "gathering_exception (+0013)",
        "PK id; FK table?, resolved_by?",
        "resolution_note; OPEN / RESOLVED",
    ),
]
svg = [
    '<svg xmlns="http://www.w3.org/2000/svg" width="1140" height="950" viewBox="0 0 1140 950">',
    '<rect width="1140" height="950" fill="#fff9ed"/>',
    '<g font-family="Arial,sans-serif" fill="#422817">',
    '<text x="40" y="45" font-size="26" font-weight="bold">SerenTable: schema 0012 / 0013</text>',
    '<text x="40" y="77" font-size="16">'
    "Local only; production not migrated. ? = nullable FK.</text>",
]
for x, label in [
    (40, "dining_table (confirmed context)"),
    (590, "app_user (participant / operator)"),
]:
    svg += [
        f'<rect x="{x}" y="105" width="510" height="58" rx="8" fill="#8b4e27"/>',
        f'<text x="{x + 18}" y="141" font-size="20" fill="white">{label}</text>',
    ]
for i, (name, key, state) in enumerate(TABLES):
    x, y = 40 + (i % 2) * 550, 200 + (i // 2) * 170
    svg += [
        f'<rect x="{x}" y="{y}" width="510" height="135" rx="8" fill="white" stroke="#d7c6af"/>',
        f'<rect x="{x}" y="{y}" width="510" height="37" rx="8" fill="#f4eadb"/>',
    ]
    for offset, label, size in [(26, name, 20), (67, key, 16), (101, state, 16)]:
        svg.append(f'<text x="{x + 16}" y="{y + offset}" font-size="{size}">{escape(label)}</text>')
svg += [
    '<text x="40" y="918" font-size="16">'
    "FK table = dining_table; user / actor / reviewer = app_user. Full relationships: .mmd.</text>",
    "</g></svg>",
]
(ROOT / "docs/design/erd/feedback-audit-physical.svg").write_text("\n".join(svg))
