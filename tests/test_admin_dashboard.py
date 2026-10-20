"""Work #9 A: the operator dashboard through HTTP and the real isolated PostgreSQL.

Expected counts come from the small hand-built scenarios below, not from the queries.
"""

import os
import subprocess
import sys
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.gatherings import run_gathering_jobs
from serentable.main import app
from serentable.matching import run_due_matches
from serentable.notifications import dispatch_notifications, enqueue_notification
from sqlalchemy import text
from support import login, send, truncate, wait_for_slot_matching
from test_applications import apply, create_slot, make_ready
from test_attendance import move_slot, user_id
from test_matching_runner import apply_and_pay, due_slot, prepare
from test_notifications import Provider, configure, subscription
from test_payments import pay

PATH = "/api/admin/dashboard"


@pytest.fixture(autouse=True)
def dashboard_database(seeded_database):
    truncate(
        "event_slot, participant_profile, consent_record, app_notification, "
        "push_subscription, gathering_exception, safety_report"
    )


def test_dashboard_is_operator_only_and_rejects_an_unknown_slot():
    with TestClient(app) as operator, TestClient(app) as member, TestClient(app) as anonymous:
        login(operator, "operator")
        login(member)
        assert operator.get(PATH).json()["slots"] == []
        slot = create_slot(operator)
        assert member.get(PATH).status_code == 403
        assert anonymous.get(PATH).status_code == 401
        assert member.get(f"{PATH}?event_slot_id={slot}").status_code == 403
        missing = operator.get(f"{PATH}?event_slot_id={uuid.uuid4()}")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "event_slot_not_found"
        assert operator.get(f"{PATH}?event_slot_id=nope").status_code == 422
        listed = operator.get(PATH)
        assert listed.status_code == 200
        assert listed.headers["cache-control"] == "no-store"
        assert [item["event_slot"]["id"] for item in listed.json()["slots"]] == [slot]


def slot_view(operator, slot):
    response = operator.get(f"{PATH}?event_slot_id={slot}")
    assert response.status_code == 200, response.text
    (item,) = response.json()["slots"]
    assert item["event_slot"]["id"] == slot
    return item


def test_application_and_payment_states_are_counted_per_slot():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        p1, p2, p3, p4 = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate((p1, p2, p3, p4), 1):
            login(participant, f"participant-0{index}")
            make_ready(participant)
        first = create_slot(operator, days=7)
        second = create_slot(operator, days=8)
        paid = apply(p1, [first]).json()["application"]["id"]
        assert pay(p1, paid, "single").json()["payment"]["state"] == "PAID"
        failed = apply(p2, [first]).json()["application"]["id"]
        assert pay(p2, failed, "single", simulate_failure=True).status_code == 201
        assert apply(p3, [first, second]).status_code == 201
        canceled = apply(p4, [first]).json()["application"]["id"]
        assert send(p4, "POST", f"/api/me/applications/{canceled}/cancel").status_code == 200
        view = slot_view(operator, first)
        assert view["applications"] == {"DRAFT": 0, "SUBMITTED": 3, "CANCELED": 1}
        assert view["payments"] == {"PENDING": 0, "PAID": 1, "FAILED": 1, "REFUNDED": 0}
        other = slot_view(operator, second)
        assert other["applications"] == {"DRAFT": 0, "SUBMITTED": 1, "CANCELED": 0}
        assert other["payments"] == {"PENDING": 0, "PAID": 0, "FAILED": 0, "REFUNDED": 0}
        everything = operator.get(PATH).json()["slots"]
        assert [item["event_slot"]["id"] for item in everything] == [second, first]


def extra_participants(count):
    """Synthetic participants beyond the four seeded ones (same demo password hash)."""
    names = [f"participant-w9a-{index}" for index in range(1, count + 1)]
    with database_engine().begin() as connection:
        for name in names:
            connection.execute(
                text("""INSERT INTO app_user(id,login_id,password_hash,role,active)
                SELECT gen_random_uuid(),:name,password_hash,role,true
                FROM app_user WHERE login_id='participant-01' ON CONFLICT(login_id) DO NOTHING"""),
                {"name": name},
            )
    return names


def run_worker_once():
    process = subprocess.run(
        [sys.executable, "-m", "serentable.worker", "--once"],
        env=os.environ.copy(),
        capture_output=True,
        timeout=60,
    )
    assert process.returncode == 0, process.stderr


def test_worker_results_show_matching_venue_room_push_and_exception_counts():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        seated = [stack.enter_context(TestClient(app)) for _ in range(4)]
        unseated = [stack.enter_context(TestClient(app)) for _ in range(3)]
        login(operator, "operator")
        for index, member in enumerate(seated, 1):
            prepare(member, f"participant-0{index}")
        for member, name in zip(unseated, extra_participants(3), strict=True):
            prepare(member, name)
        # Only the first seated member has a push subscription.
        subscribe(seated[0])
        table_slot = due_slot(operator, region="hongdae", close_in=5)
        short_slot = due_slot(operator, region="gangnam", close_in=5)
        later_slot = create_slot(operator, days=9)
        for member in seated:
            apply_and_pay(member, table_slot)
        for member in unseated:
            apply_and_pay(member, short_slot)
        wait_for_slot_matching(table_slot)
        wait_for_slot_matching(short_slot)
        run_worker_once()
        table_view = slot_view(operator, table_slot)
        assert table_view["matching"] == {
            "run_state": "SUCCEEDED",
            "attempt": 1,
            "confirmed_count": 4,
            "table_count": 1,
            "alternative_offered_count": 0,
        }
        # No inventory was registered: one table waits for a venue with an open exception.
        assert table_view["gathering"] == {"venue_assigned": 0, "venue_pending": 1, "room_count": 1}
        # CONFIRMED and VENUE_PENDING for the one subscriber; no VAPID key in the test worker.
        assert table_view["push"] == {"PENDING": 0, "SENT": 0, "FAILED": 0, "UNAVAILABLE": 2}
        assert table_view["open_exception_count"] == 1
        short_view = slot_view(operator, short_slot)
        assert short_view["matching"] == {
            "run_state": "SUCCEEDED",
            "attempt": 1,
            "confirmed_count": 0,
            "table_count": 0,
            "alternative_offered_count": 3,
        }
        assert short_view["gathering"] == {"venue_assigned": 0, "venue_pending": 0, "room_count": 0}
        assert short_view["push"] == {"PENDING": 0, "SENT": 0, "FAILED": 0, "UNAVAILABLE": 0}
        assert short_view["open_exception_count"] == 0
        later_view = slot_view(operator, later_slot)
        assert later_view["matching"] == {
            "run_state": None,
            "attempt": None,
            "confirmed_count": 0,
            "table_count": 0,
            "alternative_offered_count": 0,
        }


def confirmed_table(operator, members, close_in=4):
    """One slot whose four members are seated at one table by the matching runner."""
    for index, member in enumerate(members, 1):
        prepare(member, f"participant-0{index}")
    slot = due_slot(operator, close_in=close_in)
    for member in members:
        apply_and_pay(member, slot)
    wait_for_slot_matching(slot)
    assert run_due_matches()[0]["seated_count"] == 4
    return slot


def subscribe(member):
    response = send(member, "POST", "/api/me/push-subscriptions", subscription())
    assert response.status_code in (200, 201), response.text


def test_exhausted_push_retries_count_as_open_exceptions_of_their_table_slot(monkeypatch):
    configure(monkeypatch)
    provider = Provider(503)
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        slot = confirmed_table(operator, members)
        subscribe(members[0])
        run_gathering_jobs()
        # A notification that names no table belongs to no slot.
        with database_engine().begin() as connection:
            enqueue_notification(
                connection,
                user_id(members[0]),
                "delivery:unrelated",
                "TEST",
                "제목",
                "본문",
                "/participant",
                datetime.now(timezone.utc),
            )
        assert slot_view(operator, slot)["push"] == {
            "PENDING": 2,
            "SENT": 0,
            "FAILED": 0,
            "UNAVAILABLE": 0,
        }
        for _ in range(3):
            assert dispatch_notifications(session=provider) == 3
            with database_engine().begin() as connection:
                connection.execute(
                    text("UPDATE push_delivery SET next_attempt_at=CURRENT_TIMESTAMP")
                )
        view = slot_view(operator, slot)
        assert view["push"] == {"PENDING": 0, "SENT": 0, "FAILED": 2, "UNAVAILABLE": 0}
        # The venue exception plus one per exhausted table delivery; the unrelated one is not.
        assert view["open_exception_count"] == 3


RATINGS = dict.fromkeys(
    ("table_rating", "conversation_rating", "venue_rating", "rejoin_intent", "recommend_intent"), 4
)


def test_attendance_feedback_and_open_reports_are_counted_without_personal_data():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        slot = confirmed_table(operator, members)
        with database_engine().connect() as connection:
            table = str(connection.execute(text("SELECT id FROM dining_table")).scalar_one())
        ids = [user_id(member) for member in members]
        move_slot(slot, starts_in=10, ends_in=130)
        for member in members[:2]:
            path = f"/api/me/tables/{table}/check-in"
            assert send(member, "POST", path).status_code == 201
        before = slot_view(operator, slot)["attendance"]
        # Before the end nobody is a no-show candidate and feedback is not open yet.
        assert before == {
            "check_in_count": 2,
            "no_show_candidate_count": 0,
            "feedback_submitted": 0,
            "feedback_eligible": 0,
            "feedback_rate": None,
        }
        move_slot(slot, starts_in=-130, ends_in=-10)
        review = f"/api/admin/no-show-candidates/{table}/{ids[2]}"
        assert send(operator, "POST", review, {"decision": "EXCUSED"}).status_code == 201
        feedback = f"/api/me/tables/{table}/feedback"
        assert send(members[0], "PUT", feedback, RATINGS).status_code == 200
        reports = [
            send(
                member,
                "POST",
                "/api/me/reports",
                {"dining_table_id": table, "reported_id": ids[3], "reason_code": "other"},
            )
            for member in members[:2]
        ]
        assert [report.status_code for report in reports] == [201, 201]
        dismissed = reports[0].json()["report"]["id"]
        decision = {"decision": "DISMISSED"}
        reviewed = send(operator, "POST", f"/api/admin/reports/{dismissed}/review", decision)
        assert reviewed.status_code == 200, reviewed.text
        response = operator.get(f"{PATH}?event_slot_id={slot}")
        (view,) = response.json()["slots"]
        # Four seats: two checked in, one excused, one still awaiting review.
        assert view["attendance"] == {
            "check_in_count": 2,
            "no_show_candidate_count": 1,
            "feedback_submitted": 1,
            "feedback_eligible": 4,
            "feedback_rate": 0.25,
        }
        assert view["open_report_count"] == 1
        profile = ["테스트 식탁", "합성 이름", "010-0000-0000", "synthetic_demo"]
        for private in [*ids, "participant-0", *profile]:
            assert private not in response.text
