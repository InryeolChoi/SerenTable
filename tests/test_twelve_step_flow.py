"""Work #10: the PRD 12-step normal path for one slot, chained end to end.

Real PostgreSQL, HTTP for every participant/operator action, and the separate worker
process (`python -m serentable.worker --once`) for everything automatic. Only the isolated
slot times are moved with SQL (the fixture clock already used by the gathering, attendance
and feedback tests); there is no production clock override.

Each step is asserted individually elsewhere; this test proves they connect without any
operator action after the deadline, and that nothing is left in the exception queue.
Step 8 (failure resolution) is not a normal-path step; it is covered by
test_matching_resolution.py and frontend/e2e/matching.spec.ts.
"""

import os
import subprocess
import sys
import time
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.main import app
from sqlalchemy import text
from support import login, send, truncate
from test_applications import COMPLETE_PROFILE, apply
from test_attendance import move_slot, user_id
from test_matching_runner import apply_and_pay, due_slot, prepare

UNPAID = "participant-w10-unpaid"
RATINGS = dict.fromkeys(
    ("table_rating", "conversation_rating", "venue_rating", "rejoin_intent", "recommend_intent"), 4
)
# Everyone states "no restriction", so the verified inventory is allocated automatically.
NO_RESTRICTION = {
    **COMPLETE_PROFILE,
    "food_restrictions": {"status": "none"},
    "allergies": {"status": "none"},
}


@pytest.fixture(autouse=True)
def flow_database(seeded_database):
    tables = (
        "event_slot, participant_profile, consent_record, app_notification, "
        "gathering_exception, operator_audit, participant_exclusion"
    )
    truncate(tables)
    # One synthetic participant beyond the four seeded ones (same demo password hash).
    with database_engine().begin() as connection:
        connection.execute(
            text("""INSERT INTO app_user(id,login_id,password_hash,role,active)
            SELECT gen_random_uuid(),:login,password_hash,role,true
            FROM app_user WHERE login_id='participant-01' ON CONFLICT(login_id) DO NOTHING"""),
            {"login": UNPAID},
        )
    yield
    # Remove the extra account so later tests still see only the four seeded participants.
    truncate(tables)
    with database_engine().begin() as connection:
        connection.execute(
            text("""DELETE FROM auth_session WHERE user_id IN
            (SELECT id FROM app_user WHERE login_id=:login)"""),
            {"login": UNPAID},
        )
        connection.execute(text("DELETE FROM app_user WHERE login_id=:login"), {"login": UNPAID})


def wait_past_close(deadline):
    """Sleep until just after a slot's real close, measured from its creation."""
    time.sleep(max(0, deadline - time.monotonic()))


def run_worker():
    """One cycle of the separate runner process: matching, gathering, feedback, push."""
    process = subprocess.run(
        [sys.executable, "-m", "serentable.worker", "--once"],
        env=os.environ.copy(),
        capture_output=True,
        timeout=60,
    )
    assert process.returncode == 0, process.stderr
    assert b"unavailable" not in process.stderr, process.stderr


def register_inventory(operator, slot):
    created = send(
        operator,
        "POST",
        "/api/admin/venue-inventory",
        {
            "event_slot_id": slot,
            "name": "12단계 가상 식당",
            "address": "합성 주소",
            "map_url": "https://map.naver.com/",
            "price_krw": 15000,
            "capacity": 6,
        },
    )
    assert created.status_code == 201, created.text


def table_components(slot):
    with database_engine().connect() as connection:
        return connection.execute(
            text("SELECT components FROM dining_table WHERE event_slot_id=:slot"), {"slot": slot}
        ).scalar_one()


def test_one_slot_runs_all_twelve_steps_without_operator_action_after_the_deadline():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        unpaid = stack.enter_context(TestClient(app))
        login(operator, "operator")
        for index, member in enumerate(members, 1):
            prepare(member, f"participant-0{index}")
            assert send(member, "PUT", "/api/me/profile", NO_RESTRICTION).status_code == 200
        prepare(unpaid, UNPAID)
        ids = [user_id(member) for member in members]

        # Operator pre-work before the deadline: one slot and its verified inventory.
        slot = due_slot(operator, close_in=15)
        deadline = time.monotonic() + 15.6
        register_inventory(operator, slot)

        # Step 1: different profiles choose the slot and apply. Four pay; one does not.
        applications = [apply_and_pay(member, slot) for member in members]
        unpaid_created = apply(unpaid, [slot])
        assert unpaid_created.status_code == 201, unpaid_created.text
        audit_before_deadline = operator.get("/api/admin/audit").json()["audit"]
        assert sorted(row["action"] for row in audit_before_deadline) == [
            "event_slot.create",
            "venue_inventory.create",
        ]

        # Step 2: at the matching time the separate worker matches paid applications only.
        wait_past_close(deadline)
        run_worker()
        (run,) = operator.get("/api/admin/match-runs").json()["match_runs"]
        assert (run["state"], run["attempt"], run["seated_count"]) == ("SUCCEEDED", 1, 4)
        assert unpaid.get("/api/me/applications").json()["applications"][0]["matching"] is None

        # Step 3: a 4~6 person table that meets the minimum score (ADR-0011).
        (table,) = run["tables"]
        assert 4 <= table["member_count"] <= 6
        assert float(table["score"]) >= float(run["policy"]["min_score"])
        assert table["components"]["new"] == "100.00"

        # Step 5: confirmed automatically, the single pass used once, no operator approval.
        for member, application_id in zip(members, applications, strict=True):
            (mine,) = member.get("/api/me/applications").json()["applications"]
            assert mine["id"] == application_id
            assert mine["matching"]["state"] == "CONFIRMED"
            assert mine["matching"]["table"]["member_count"] == 4
            (right,) = member.get("/api/me/entitlements").json()["entitlements"]
            assert right["state"] == "USED"

        # Step 6: the venue and the in-app room are assigned and created by the worker.
        # Step 7: the participant sees the result, venue and announcements in the room.
        gathering = members[0].get("/api/me/gatherings").json()["gatherings"][0]
        assert gathering["venue_state"] == "ASSIGNED"
        assert gathering["venue"]["name"] == "12단계 가상 식당"
        assert gathering["venue"]["reservation_name"]
        rooms = members[0].get("/api/me/rooms").json()["rooms"]
        assert [room["id"] for room in rooms] == [gathering["room_id"]]
        assert rooms[0]["member_count"] == 4
        for member in members[1:]:
            assert member.get("/api/me/rooms").json()["rooms"] == rooms
        room_path = f"/api/me/rooms/{gathering['room_id']}/messages"
        messages = members[0].get(room_path).json()["messages"]
        assert len(messages) == 2
        assert "모임이 확정되었습니다" in messages[0]["body"]
        assert "12단계 가상 식당" in messages[1]["body"]
        notified = members[0].get("/api/me/notifications").json()["notifications"]
        assert {n["kind"] for n in notified} >= {"CONFIRMED", "VENUE_ASSIGNED"}
        # Each table announcement names the caller's own table, so a client can tell tables
        # apart without guessing from text or time.
        assert {n["table_id"] for n in notified} == {gathering["id"]}
        body = members[0].get("/api/me/applications").text + str(messages)
        for secret in ("010-0000-0000", "synthetic_demo", "score", "components"):
            assert secret not in body

        # Step 9: the day-before reminder, then the in-event content, posted once each.
        move_slot(slot, starts_in=30, ends_in=150)
        run_worker()
        run_worker()
        messages = members[0].get(room_path).json()["messages"]
        assert len(messages) == 3
        assert "하루 안에 시작" in messages[-1]["body"]
        move_slot(slot, starts_in=-1, ends_in=119)
        run_worker()
        run_worker()
        messages = members[0].get(room_path).json()["messages"]
        assert len(messages) == 4
        assert "오늘의 대화 주제" in messages[-1]["body"]
        assert "아이스브레이킹" in messages[-1]["body"]

        # Step 10: everyone checks in during the event, then rates the table and people.
        for member in members:
            checked = send(member, "POST", f"/api/me/tables/{gathering['id']}/check-in")
            assert checked.status_code == 201, checked.text
        move_slot(slot, starts_in=-180, ends_in=-60)
        for member in members:
            rated = send(member, "PUT", f"/api/me/tables/{gathering['id']}/feedback", RATINGS)
            assert rated.status_code == 200, rated.text
        pairs = [(0, 1), (1, 0)]  # participant-01 and -02 both want to meet again
        for source, target in pairs:
            saved = send(
                members[source],
                "PUT",
                f"/api/me/tables/{gathering['id']}/preferences",
                {"preferences": [{"target_id": ids[target], "choice": "MEET_AGAIN"}]},
            )
            assert saved.status_code == 200, saved.text
        run_worker()
        # Nothing about the finished event is re-posted after its end.
        assert len(members[0].get(room_path).json()["messages"]) == 4

        # Step 11: the next matching counts the previous meeting, minus the mutual pair.
        next_slot = due_slot(operator, region="gangnam", close_in=12)
        deadline = time.monotonic() + 12.6
        register_inventory(operator, next_slot)
        for member in members:
            apply_and_pay(member, next_slot)
        wait_past_close(deadline)
        run_worker()
        for member in members:
            states = {
                a["matching"]["event_slot_id"]: a["matching"]["state"]
                for a in member.get("/api/me/applications").json()["applications"]
                if a["matching"]
            }
            assert states == {slot: "CONFIRMED", next_slot: "CONFIRMED"}
        # ADR-0011 new = 100 x (1 - met pairs / 6). Six pairs met; the mutual
        # MEET_AGAIN pair is not counted (ADR-0014 U08), so 5 / 6 remain.
        assert table_components(next_slot)["new"] == "16.67"

        # Step 12: the normal path needed no operator action after the deadline, and
        # no unresolved exception is left for the operator.
        actions = sorted(row["action"] for row in operator.get("/api/admin/audit").json()["audit"])
        assert actions == ["event_slot.create"] * 2 + ["venue_inventory.create"] * 2
        assert operator.get("/api/admin/exceptions", params={"state": "OPEN"}).json() == {
            "exceptions": []
        }
        assert operator.get("/api/admin/no-show-candidates").json() == {"candidates": []}
        for each in (slot, next_slot):
            view = operator.get(f"/api/admin/dashboard?event_slot_id={each}").json()["slots"][0]
            assert view["open_exception_count"] == 0
            assert view["matching"]["confirmed_count"] == 4
            assert view["gathering"]["venue_assigned"] == 1


# ADR-0011 hand calculation (same people as test_matching_plan.POOR): age 0, four men 0,
# MBTI 520/6, interest 0, trait 0 (nobody energetic/leading), new 100 -> 28 < 60.
POOR = [
    (1990, "ISTJ", "music"),
    (1998, "ENFP", "travel"),
    (1994, "ISTJ", "reading"),
    (1996, "ENFP", "exercise"),
]


def test_the_worker_dissolves_a_table_below_the_minimum_score_into_alternative_offers():
    """Step 4 at the worker boundary: an unsuitable combination is not confirmed."""
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, (member, (year, mbti, interest)) in enumerate(
            zip(members, POOR, strict=True), 1
        ):
            prepare(member, f"participant-0{index}")
            profile = {
                **NO_RESTRICTION,
                "birth_year": year,
                "gender": "남성",
                "mbtis": [mbti],
                "interests": [interest],
                "self_traits": ["calm"],
                "desired_traits": ["passionate"],
            }
            assert send(member, "PUT", "/api/me/profile", profile).status_code == 200
        slot = due_slot(operator, close_in=10)
        deadline = time.monotonic() + 10.6
        register_inventory(operator, slot)
        alternative = due_slot(operator, region="gangnam", days=9, close_in=3600)
        applications = [apply_and_pay(member, slot) for member in members]
        wait_past_close(deadline)
        run_worker()
        (run,) = operator.get("/api/admin/match-runs").json()["match_runs"]
        assert (run["state"], run["seated_count"], run["tables"]) == ("SUCCEEDED", 0, [])
        for member, application_id in zip(members, applications, strict=True):
            (mine,) = member.get("/api/me/applications").json()["applications"]
            assert mine["matching"]["state"] == "ALTERNATIVE_OFFERED"
            assert mine["matching"]["reason_code"] == "no_qualifying_table"
            assert mine["matching"]["table"] is None
            (right,) = member.get("/api/me/entitlements").json()["entitlements"]
            assert right["state"] == "HELD" and right["used_at"] is None
            offer = member.get(f"/api/me/applications/{application_id}/alternatives").json()
            assert [s["id"] for s in offer["alternatives"]] == [alternative]
        # No table, so no room or venue; still answerable before the event, so the
        # operator queue stays empty (ADR-0015: overdue only after the slot starts).
        assert members[0].get("/api/me/gatherings").json()["gatherings"] == []
        assert members[0].get("/api/me/rooms").json()["rooms"] == []
        assert operator.get("/api/admin/exceptions", params={"state": "OPEN"}).json() == {
            "exceptions": []
        }
