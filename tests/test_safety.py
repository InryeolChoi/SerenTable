"""Reports, blocks and operator sanctions through HTTP and the real isolated PostgreSQL."""

import time
import uuid
from contextlib import ExitStack
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.main import app
from serentable.matching import run_due_matches
from sqlalchemy import text
from support import SEOUL, login, send, truncate
from test_matching_runner import apply_and_pay, due_slot, prepare

SAFETY_TABLES = "participant_sanction, safety_report, participant_exclusion"


@pytest.fixture
def table(seeded_database):
    """Four confirmed members seated at one table, plus the operator."""
    truncate(f"{SAFETY_TABLES}, event_slot, participant_profile, consent_record")
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, member in enumerate(members, 1):
            prepare(member, f"participant-0{index}")
        slot = due_slot(operator, close_in=4)
        for member in members:
            apply_and_pay(member, slot)
        time.sleep(4.6)
        assert run_due_matches()[0]["seated_count"] == 4
        table_id = str(connection_scalar("SELECT id FROM dining_table"))
        ids = [member.get("/api/auth/me").json()["user"]["id"] for member in members]
        yield operator, members, ids, table_id
    # Sanctions survive event_slot truncation elsewhere; never leak them to other tests.
    truncate(SAFETY_TABLES)


def connection_scalar(sql, params=None):
    with database_engine().connect() as connection:
        return connection.execute(text(sql), params or {}).scalar()


def exclusions():
    with database_engine().connect() as connection:
        return {
            (str(row[0]), str(row[1]), row[2])
            for row in connection.execute(
                text("SELECT user_low, user_high, source FROM participant_exclusion")
            ).all()
        }


def pair(a, b, source):
    low, high = sorted((a, b))
    return (low, high, source)


def report(client, table_id, reported_id, reason="harassment", detail=None):
    return send(
        client,
        "POST",
        "/api/me/reports",
        {
            "dining_table_id": table_id,
            "reported_id": reported_id,
            "reason_code": reason,
            "detail": detail,
        },
    )


def test_a_tablemate_report_is_stored_with_its_exclusion_and_replays_unchanged(table):
    _, members, ids, table_id = table
    created = report(members[0], table_id, ids[1], detail="불편한 발언")
    assert created.status_code == 201, created.text
    body = created.json()["report"]
    assert body["state"] == "OPEN"
    assert body["reported"] == {"id": ids[1], "display_name": body["reported"]["display_name"]}
    assert exclusions() == {pair(ids[0], ids[1], "report")}
    replay = report(members[0], table_id, ids[1], detail="불편한 발언")
    assert replay.status_code == 200
    assert replay.json()["report"] == body
    assert connection_scalar("SELECT count(*) FROM safety_report") == 1


def block(client, table_id, blocked_id):
    return send(
        client,
        "POST",
        "/api/me/blocks",
        {"dining_table_id": table_id, "blocked_id": blocked_id},
    )


def test_only_confirmed_tablemates_can_be_reported_or_blocked(table):
    operator, members, ids, table_id = table
    # Prepared DB fixture: participant-04 is no longer a confirmed member of this table.
    with database_engine().begin() as connection:
        connection.execute(
            text(
                "UPDATE match_participation SET state='EXCEPTION',reason_code='test', "
                "dining_table_id=NULL WHERE user_id=:id"
            ),
            {"id": ids[3]},
        )
    for target in (ids[3], ids[0], str(uuid.uuid4())):
        assert report(members[0], table_id, target).status_code == 404
        assert block(members[0], table_id, target).status_code == 404
    assert report(members[3], table_id, ids[0]).status_code == 404
    assert report(members[0], str(uuid.uuid4()), ids[1]).status_code == 404
    assert report(operator, table_id, ids[1]).status_code == 403
    path = "/api/me/reports"
    payload = {"dining_table_id": table_id, "reported_id": ids[1], "reason_code": "other"}
    assert members[0].post(path, json=payload).status_code == 403
    assert members[0].post("/api/me/blocks", json=payload).status_code == 403
    assert report(members[0], table_id, ids[1], reason="unknown").status_code == 422
    assert report(members[0], table_id, ids[1], detail="가" * 1001).status_code == 422
    assert exclusions() == set()
    assert connection_scalar("SELECT count(*) FROM safety_report") == 0


def test_a_block_records_only_a_symmetric_exclusion_and_replays(table):
    _, members, ids, table_id = table
    first = block(members[0], table_id, ids[2])
    assert first.status_code == 200, first.text
    assert first.json() == {"blocked": True}
    assert block(members[0], table_id, ids[2]).json() == {"blocked": True}
    assert exclusions() == {pair(ids[0], ids[2], "block")}
    assert connection_scalar("SELECT count(*) FROM safety_report") == 0


def test_a_report_and_its_exclusion_commit_together(table, monkeypatch):
    import serentable.safety as safety

    _, members, ids, table_id = table

    def failing(connection, a, b, source):
        raise RuntimeError("exclusion write failed")

    # Fault injection at the exclusion write: the report insert before it must roll back.
    with monkeypatch.context() as patch, pytest.raises(RuntimeError):
        patch.setattr(safety, "record_exclusion", failing)
        report(members[0], table_id, ids[1])
    assert connection_scalar("SELECT count(*) FROM safety_report") == 0
    assert report(members[0], table_id, ids[1]).status_code == 201
    assert exclusions() == {pair(ids[0], ids[1], "report")}


def review(client, report_id, decision):
    return send(client, "POST", f"/api/admin/reports/{report_id}/review", {"decision": decision})


def test_the_reporter_sees_tablemates_and_only_their_own_reports(table):
    _, members, ids, table_id = table
    path = f"/api/me/tables/{table_id}/safety"
    view = members[0].get(path)
    assert view.status_code == 200
    assert sorted(mate["id"] for mate in view.json()["tablemates"]) == sorted(ids[1:])
    assert all(set(mate) == {"id", "display_name"} for mate in view.json()["tablemates"])
    assert view.json()["reports"] == []
    created = report(members[0], table_id, ids[1], detail="원문").json()["report"]
    assert members[0].get(path).json()["reports"] == [created]
    assert members[2].get(path).json()["reports"] == []
    assert members[0].get(f"/api/me/tables/{uuid.uuid4()}/safety").status_code == 404


def test_the_reported_participant_never_observes_the_report(table):
    _, members, ids, table_id = table
    before = {
        path: members[1].get(path).json()
        for path in (
            f"/api/me/tables/{table_id}/safety",
            "/api/me/applications",
            "/api/me/gatherings",
            "/api/me/notifications",
            "/api/me/rooms",
            "/api/auth/me",
        )
    }
    detail = "피신고자에게-보이면-안-되는-원문"
    assert report(members[0], table_id, ids[1], detail=detail).status_code == 201
    assert block(members[0], table_id, ids[1]).status_code == 200
    for path, previous in before.items():
        response = members[1].get(path)
        assert response.status_code == 200
        assert response.json() == previous, path
        assert detail not in response.text
    assert members[1].get("/api/admin/reports").status_code == 403


def test_review_changes_only_the_report_state_and_the_separation_persists(table):
    operator, members, ids, table_id = table
    created = report(members[0], table_id, ids[1], detail="원문").json()["report"]
    listed = operator.get("/api/admin/reports")
    assert listed.status_code == 200
    (row,) = listed.json()["reports"]
    assert row["id"] == created["id"]
    assert row["state"] == "OPEN"
    assert row["detail"] == "원문"
    assert row["reporter"]["id"] == ids[0]
    assert row["reported"]["id"] == ids[1]
    dismissed = review(operator, created["id"], "DISMISSED")
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["report"]["state"] == "DISMISSED"
    assert review(operator, created["id"], "DISMISSED").json() == dismissed.json()
    assert review(operator, created["id"], "CONFIRMED").status_code == 409
    assert review(operator, str(uuid.uuid4()), "CONFIRMED").status_code == 404
    assert review(operator, created["id"], "OPEN").status_code == 422
    assert exclusions() == {pair(ids[0], ids[1], "report")}
    assert (
        members[0].get(f"/api/me/tables/{table_id}/safety").json()["reports"][0]["state"]
        == "DISMISSED"
    )


def test_operator_endpoints_refuse_participants_and_require_csrf(table):
    operator, members, ids, table_id = table
    created = report(members[0], table_id, ids[1]).json()["report"]
    sanction = {"user_id": ids[1], "kind": "WARNING"}
    for client in members[:2]:
        assert client.get("/api/admin/reports").status_code == 403
        assert client.get("/api/admin/sanctions").status_code == 403
        assert review(client, created["id"], "CONFIRMED").status_code == 403
        assert send(client, "POST", "/api/admin/sanctions", sanction).status_code == 403
    review_path = f"/api/admin/reports/{created['id']}/review"
    assert operator.post(review_path, json={"decision": "CONFIRMED"}).status_code == 403
    assert operator.post("/api/admin/sanctions", json=sanction).status_code == 403
    assert connection_scalar("SELECT state FROM safety_report") == "OPEN"
    assert connection_scalar("SELECT count(*) FROM participant_sanction") == 0


def sanction(operator, user_id, kind, **extra):
    return send(
        operator, "POST", "/api/admin/sanctions", {"user_id": user_id, "kind": kind} | extra
    )


def apply_to(client, slot_id):
    return send(
        client,
        "POST",
        "/api/me/applications",
        {"request_key": str(uuid.uuid4()), "event_slot_ids": [slot_id]},
    )


def test_sanctions_validate_their_shape_and_link_only_confirmed_reports(table):
    operator, members, ids, table_id = table
    created = report(members[0], table_id, ids[1]).json()["report"]
    future = (datetime.now(SEOUL) + timedelta(days=7)).isoformat()
    past = (datetime.now(SEOUL) - timedelta(minutes=1)).isoformat()
    assert sanction(operator, ids[1], "SUSPENSION").status_code == 422
    assert sanction(operator, ids[1], "SUSPENSION", ends_at=past).status_code == 422
    assert sanction(operator, ids[1], "WARNING", ends_at=future).status_code == 422
    assert sanction(operator, str(uuid.uuid4()), "WARNING").status_code == 404
    assert sanction(operator, ids[1], "WARNING", report_id=created["id"]).status_code == 409
    assert review(operator, created["id"], "CONFIRMED").status_code == 200
    assert sanction(operator, ids[2], "WARNING", report_id=created["id"]).status_code == 404
    first = sanction(operator, ids[1], "WARNING", report_id=created["id"])
    assert first.status_code == 201, first.text
    replay = sanction(operator, ids[1], "WARNING", report_id=created["id"])
    assert replay.status_code == 200
    assert replay.json() == first.json()
    (listed,) = operator.get("/api/admin/sanctions").json()["sanctions"]
    assert listed == first.json()["sanction"]
    assert listed["user"]["id"] == ids[1]
    assert listed["restricting"] is False


def test_active_suspension_and_ban_block_new_applications_but_warnings_do_not(table):
    operator, members, ids, _ = table
    slot = due_slot(operator, close_in=3600, days=14)
    assert sanction(operator, ids[0], "WARNING").status_code == 201
    assert apply_to(members[0], slot).status_code == 201
    ends = datetime.now(SEOUL) + timedelta(seconds=3)
    assert sanction(operator, ids[1], "SUSPENSION", ends_at=ends.isoformat()).status_code == 201
    restricted = apply_to(members[1], slot)
    assert restricted.status_code == 403
    assert restricted.json()["detail"] == "participation_restricted"
    assert sanction(operator, ids[2], "PERMANENT_BAN").status_code == 201
    assert apply_to(members[2], slot).json()["detail"] == "participation_restricted"
    time.sleep(max(0.0, (ends - datetime.now(SEOUL)).total_seconds()) + 0.3)
    assert apply_to(members[1], slot).status_code == 201
    assert apply_to(members[2], slot).status_code == 403
    states = {
        row["user"]["id"]: row["restricting"]
        for row in operator.get("/api/admin/sanctions").json()["sanctions"]
    }
    assert states == {ids[0]: False, ids[1]: False, ids[2]: True}


def serialize_api_with_matching(request, user_id):
    """Hold the real worker coordination lock while a second connection serves HTTP.

    A safety write must wait before taking the participant row lock; otherwise a worker
    could calculate H5 before the exclusion commits and confirm the pair afterwards.
    """
    from concurrent.futures import ThreadPoolExecutor

    from serentable.match_resolution import lock_matching

    with ThreadPoolExecutor(max_workers=1) as pool:
        with database_engine().begin() as connection:
            lock_matching(connection)
            pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            pending = pool.submit(request)
            deadline = time.monotonic() + 5
            blocked = False
            while time.monotonic() < deadline and not pending.done():
                # PostgreSQL caches statistics within a transaction; refresh this
                # observer so an API that starts after the first poll is visible.
                connection.execute(text("SELECT pg_stat_clear_snapshot()"))
                blocked = connection.execute(
                    text("""SELECT EXISTS(SELECT 1 FROM pg_stat_activity
                    WHERE datname=current_database() AND wait_event='advisory'
                      AND :pid=ANY(pg_blocking_pids(pid)))"""),
                    {"pid": pid},
                ).scalar_one()
                if blocked:
                    break
                time.sleep(0.01)
            assert blocked, "safety/preference write bypassed the active matching transaction"
            # Matching inserts reference app_user. Locking this row before the shared
            # matching lock would cause a cycle; NOWAIT catches that lock-order bug.
            connection.execute(
                text("SELECT id FROM app_user WHERE id=:id FOR KEY SHARE NOWAIT"),
                {"id": user_id},
            )
        return pending.result(timeout=5)


@pytest.mark.parametrize("action", ["report", "block"])
def test_safety_changes_wait_for_matching_before_locking_participants(table, action):
    _, members, ids, table_id = table
    request = (
        (lambda: report(members[0], table_id, ids[1]))
        if action == "report"
        else (lambda: block(members[0], table_id, ids[1]))
    )
    saved = serialize_api_with_matching(request, ids[0])
    assert saved.status_code in (200, 201), saved.text
    assert pair(ids[0], ids[1], action) in exclusions()
