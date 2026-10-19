"""Work #8 T4: participant history, next-slot recommendations and feedback in matching.

Every scenario builds real confirmed tables with the matching runner on PostgreSQL and
reads the result over HTTP; only the isolated slot times are moved with SQL.
"""

import os
import subprocess
import sys
import time
from contextlib import ExitStack
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.main import app
from sqlalchemy import text
from support import SEOUL, login, send, truncate

RATINGS = {
    "table_rating": 5,
    "conversation_rating": 4,
    "venue_rating": 4,
    "rejoin_intent": 5,
    "recommend_intent": 4,
}
# A past Saturday 19:00 in Seoul (2025-03-01 was a Saturday).
PAST_SATURDAY = "2025-03-01 19:00:00+09"
EXTRA = [f"w8t4-extra-{i}" for i in range(1, 5)]


def extra_accounts():
    """Four more synthetic participants than the shared seed provides."""
    from serentable.auth import password_hasher

    hashed = password_hasher.hash("synthetic-participant-password")
    with database_engine().begin() as connection:
        for login_id in EXTRA:
            connection.execute(
                text("""INSERT INTO app_user(id,login_id,password_hash,role,active)
                VALUES(gen_random_uuid(),:login,:hash,'participant',true)
                ON CONFLICT(login_id) DO NOTHING"""),
                {"login": login_id, "hash": hashed},
            )


def move_slot(slot, starts_sql):
    """Fixture clock: place one isolated slot at `starts_sql`, already matched."""
    with database_engine().begin() as connection:
        connection.execute(
            text(f"""UPDATE event_slot SET starts_at={starts_sql},
            ends_at={starts_sql}+interval '2 hours',
            matches_at=LEAST(now(),{starts_sql})-interval '1 day',
            closes_at=LEAST(now(),{starts_sql})-interval '1 day 1 minute'
            WHERE id=:slot"""),
            {"slot": slot},
        )


@pytest.fixture
def first_table(seeded_database):
    """participant-01..04 confirmed at one hongdae table by the real runner."""
    from serentable.matching import run_due_matches
    from test_matching_runner import apply_and_pay, due_slot, prepare

    truncate(
        "event_slot, participant_profile, consent_record, app_notification, participant_exclusion"
    )
    extra_accounts()
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        extras = [stack.enter_context(TestClient(app)) for _ in EXTRA]
        login(operator, "operator")
        for i, member in enumerate(members, 1):
            prepare(member, f"participant-0{i}")
        for login_id, extra in zip(EXTRA, extras, strict=True):
            prepare(extra, login_id)
        slot = due_slot(operator, close_in=4)
        for member in members:
            apply_and_pay(member, slot)
        time.sleep(4.6)
        assert run_due_matches()[0]["seated_count"] == 4
        table_id = members[0].get("/api/me/gatherings").json()["gatherings"][0]["id"]
        yield {
            "operator": operator,
            "members": members,
            "extras": extras,
            "ids": [m.get("/api/auth/me").json()["user"]["id"] for m in members],
            "extra_ids": [e.get("/api/auth/me").json()["user"]["id"] for e in extras],
            "slot": slot,
            "id": table_id,
        }


def history(client):
    response = client.get("/api/me/history")
    assert response.status_code == 200, response.text
    return response.json()["tables"]


def test_history_reports_own_flags_and_open_windows(first_table):
    member, mate, *_ = first_table["members"]
    (card,) = history(member)
    assert card["table_id"] == first_table["id"]
    assert card["event_slot_id"] == first_table["slot"]
    assert card["region"] == {"code": "hongdae", "name": "홍대"}
    assert card["starts_at"].endswith("+09:00")
    flags = ("checked_in", "feedback_submitted", "check_in_open", "feedback_open")
    assert {k: card[k] for k in flags} == dict.fromkeys(flags, False)

    move_slot(first_table["slot"], "now()+interval '10 minutes'")
    assert history(member)[0]["check_in_open"] is True
    assert send(member, "POST", f"/api/me/tables/{first_table['id']}/check-in").status_code == 201
    card = history(member)[0]
    assert card["checked_in"] is True and card["feedback_open"] is False

    move_slot(first_table["slot"], "now()-interval '3 hours'")
    card = history(member)[0]
    assert card["check_in_open"] is False and card["feedback_open"] is True
    saved = send(member, "PUT", f"/api/me/tables/{first_table['id']}/feedback", RATINGS)
    assert saved.status_code == 200, saved.text
    assert history(member)[0]["feedback_submitted"] is True

    # A tablemate sees only their own flags; nobody's choices or ratings leak.
    (other,) = history(mate)
    assert other["checked_in"] is False and other["feedback_submitted"] is False
    body = mate.get("/api/me/history").text
    for secret in [*first_table["ids"], "table_rating", "MEET_AGAIN", "AVOID"]:
        assert secret not in body
    # A participant who never sat at the table has no history, and operators have none.
    assert history(first_table["extras"][0]) == []
    assert first_table["operator"].get("/api/me/history").status_code == 403
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/me/history").status_code == 401


def open_slot(operator, region, weekday, weeks):
    """A recruiting slot on an ISO weekday at 19:00 Seoul, `weeks` weeks from now."""
    today = datetime.now(SEOUL)
    day = today + timedelta(days=(weekday - today.isoweekday()) % 7 + 7 * weeks)
    starts = day.replace(hour=19, minute=0, second=0, microsecond=0)
    response = send(
        operator,
        "POST",
        "/api/admin/event-slots",
        {
            "region_code": region,
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "closes_at": (starts - timedelta(days=2)).isoformat(),
            "matches_at": (starts - timedelta(days=1)).isoformat(),
            "capacity": 24,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["event_slot"]["id"], starts


def recommendations(client):
    response = client.get("/api/me/recommendations")
    assert response.status_code == 200, response.text
    return [
        (item["event_slot"]["id"], item["reason"]) for item in response.json()["recommendations"]
    ]


def test_recommendations_put_well_rated_then_attended_places_first(first_table):
    from test_applications import apply

    operator = first_table["operator"]
    rater, low_rater, silent, _ = first_table["members"]
    table = first_table["id"]
    # rater checks in and rates the Saturday hongdae table 5; low_rater rates it 2.
    move_slot(first_table["slot"], "now()+interval '10 minutes'")
    assert send(rater, "POST", f"/api/me/tables/{table}/check-in").status_code == 201
    move_slot(first_table["slot"], f"timestamptz '{PAST_SATURDAY}'")
    for client, score in ((rater, 5), (low_rater, 2)):
        saved = send(
            client, "PUT", f"/api/me/tables/{table}/feedback", RATINGS | {"table_rating": score}
        )
        assert saved.status_code == 200, saved.text

    jamsil_sat = open_slot(operator, "jamsil", 6, 1)
    gangnam_wed = open_slot(operator, "gangnam", 3, 1)
    hongdae_wed = open_slot(operator, "hongdae", 3, 2)
    hongdae_sat_late = open_slot(operator, "hongdae", 6, 3)
    hongdae_sat = open_slot(operator, "hongdae", 6, 2)
    applied = open_slot(operator, "euljiro", 1, 1)
    assert apply(rater, [applied[0]]).status_code == 201

    def ids(*slots):
        return [slot[0] for slot in sorted(slots, key=lambda slot: slot[1])]

    rated = "지난 홍대 토요일 모임을 높게 평가하셨어요."
    attended = "참석하셨던 홍대 지역의 모임이에요."
    upcoming = "모집 중인 가까운 일정이에요."
    # The slot already applied to is left out; ties fall back to the start time.
    assert recommendations(rater) == [
        (hongdae_sat[0], rated),
        (hongdae_sat_late[0], rated),
        (hongdae_wed[0], attended),
        *[(slot, upcoming) for slot in ids(jamsil_sat, gangnam_wed)],
    ]
    plain = [
        (slot, upcoming)
        for slot in ids(
            jamsil_sat, gangnam_wed, hongdae_wed, hongdae_sat_late, hongdae_sat, applied
        )
    ]
    # A low rating without a check-in, or no feedback at all, hides and blocks nothing.
    assert recommendations(low_rater) == plain
    assert recommendations(silent) == plain
    assert first_table["operator"].get("/api/me/recommendations").status_code == 403


def components(slot):
    with database_engine().connect() as connection:
        return [
            (sorted(str(u) for u in users), comp)
            for users, comp in connection.execute(
                text("""SELECT array_agg(a.user_id),t.components FROM dining_table t
                JOIN table_assignment a ON a.dining_table_id=t.id
                WHERE t.event_slot_id=:slot GROUP BY t.id,t.components"""),
                {"slot": slot},
            ).all()
        ]


def seated_by_separate_worker(operator, slot):
    """One cycle of the real runner process; the result is read back over HTTP."""
    process = subprocess.run(
        [sys.executable, "-m", "serentable.worker", "--once"],
        env=os.environ.copy(),
        capture_output=True,
        timeout=60,
    )
    assert process.returncode == 0, process.stderr
    runs = operator.get("/api/admin/match-runs").json()["match_runs"]
    (run,) = [run for run in runs if run["event_slot"]["id"] == slot]
    return run["seated_count"]


@pytest.mark.parametrize("runner", ["in_process", "separate_worker"])
def test_the_next_matching_separates_excluded_pairs_and_spares_mutual_meet_again(
    first_table, runner
):
    from serentable.matching import run_due_matches
    from test_matching_runner import apply_and_pay, due_slot

    p1, p2, p3, p4 = first_table["members"]
    i1, i2, i3, i4 = first_table["ids"]
    table = first_table["id"]
    move_slot(first_table["slot"], f"timestamptz '{PAST_SATURDAY}'")

    def prefer(client, choices):
        body = {"preferences": [{"target_id": t, "choice": c} for t, c in choices]}
        saved = send(client, "PUT", f"/api/me/tables/{table}/preferences", body)
        assert saved.status_code == 200, saved.text

    prefer(p1, [(i2, "MEET_AGAIN"), (i3, "AVOID")])  # mutual with p2; p1 avoids p3
    prefer(p2, [(i1, "MEET_AGAIN"), (i4, "MEET_AGAIN")])
    prefer(p4, [(i2, "MEET_AGAIN")])  # mutual wishes cannot override a later report
    prefer(p3, [(i4, "MEET_AGAIN")])  # one-sided: p4 never answers in kind
    report = {"dining_table_id": table, "reported_id": i4, "reason_code": "other"}
    assert send(p2, "POST", "/api/me/reports", report).status_code == 201
    block = {"dining_table_id": table, "blocked_id": i1}
    assert send(p4, "POST", "/api/me/blocks", block).status_code in (200, 201)

    slot = due_slot(first_table["operator"], region="gangnam", close_in=6)
    for client in [*first_table["members"], *first_table["extras"]]:
        apply_and_pay(client, slot)
    time.sleep(6.6)
    if runner == "in_process":
        (summary,) = run_due_matches()
        seated = summary["seated_count"]
    else:
        # PRD step 4 through the deployed shape: the separate worker repairs the excluded
        # pairs inside one run and still seats everyone.
        seated = seated_by_separate_worker(first_table["operator"], slot)
    assert seated == 8

    excluded = [{i1, i3}, {i2, i4}, {i1, i4}]
    tables = components(slot)
    for users, _ in tables:
        assert not any(pair <= set(users) for pair in excluded), users
    new = {frozenset(users) & {i1, i2, i3, i4}: comp["new"] for users, comp in tables}
    # ADR-0011 new = 100 x (1 - met pairs / 6): the mutual pair is not "previously met",
    # the one-sided pair still is.
    assert new == {frozenset({i1, i2}): "100.00", frozenset({i3, i4}): "83.33"}

    # The second table appears in each member's history as upcoming, after nothing else.
    cards = history(p1)
    assert [card["event_slot_id"] for card in cards] == [slot, first_table["slot"]]


def test_recommendations_exclude_overlapping_confirmations_but_keep_adjacent_slots(first_table):
    operator = first_table["operator"]
    member = first_table["members"][0]

    # The existing confirmed table is at day +7, 19:00..21:00. Two different
    # regions still conflict in time; the interval beginning at its end does not.
    with database_engine().connect() as connection:
        starts, ends = connection.execute(
            text("SELECT starts_at,ends_at FROM event_slot WHERE id=:id"),
            {"id": first_table["slot"]},
        ).one()

    def create(region, start):
        response = send(
            operator,
            "POST",
            "/api/admin/event-slots",
            {
                "region_code": region,
                "starts_at": start.isoformat(),
                "ends_at": (start + timedelta(hours=2)).isoformat(),
                "closes_at": (start - timedelta(days=2)).isoformat(),
                "matches_at": (start - timedelta(days=1)).isoformat(),
                "capacity": 24,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["event_slot"]["id"]

    create("jamsil", starts)
    adjacent = create("gangnam", ends)
    assert [slot for slot, _ in recommendations(member)] == [adjacent]


def test_recommendations_follow_active_sanctions_without_penalizing_warnings(first_table):
    from test_safety import sanction

    operator = first_table["operator"]
    member = first_table["members"][0]
    user_id = first_table["ids"][0]
    slot, _ = open_slot(operator, "jamsil", 6, 3)
    assert [item[0] for item in recommendations(member)] == [slot]
    assert sanction(operator, user_id, "WARNING").status_code == 201
    assert [item[0] for item in recommendations(member)] == [slot]
    assert sanction(operator, user_id, "PERMANENT_BAN").status_code == 201
    assert recommendations(member) == []
