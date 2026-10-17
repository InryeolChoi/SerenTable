"""Work7 inventory and gathering behavior through HTTP and real PostgreSQL."""

import pytest
from fastapi.testclient import TestClient
from serentable.main import app
from support import login, send, truncate
from test_applications import create_slot


@pytest.fixture(autouse=True)
def gathering_database(seeded_database):
    truncate("event_slot, participant_profile, consent_record, app_notification")


def test_operator_registers_inventory_and_participants_cannot_manage_it():
    with TestClient(app) as operator, TestClient(app) as member:
        login(operator, "operator")
        login(member)
        slot = create_slot(operator)
        payload = {
            "event_slot_id": slot,
            "name": "합성 식당",
            "address": "가상 주소",
            "map_url": "https://map.naver.com/",
            "price_krw": 15000,
            "capacity": 6,
        }
        assert send(member, "POST", "/api/admin/venue-inventory", payload).status_code == 403
        created = send(operator, "POST", "/api/admin/venue-inventory", payload)
        assert created.status_code == 201, created.text
        rows = operator.get("/api/admin/venue-inventory").json()["inventory"]
        assert rows[0]["id"] == created.json()["inventory"]["id"]
        assert member.get("/api/admin/venue-inventory").status_code == 403
        assert operator.post("/api/admin/venue-inventory", json=payload).status_code == 403


def test_unsafe_map_url_is_rejected_without_fetching_it():
    with TestClient(app) as operator:
        login(operator, "operator")
        slot = create_slot(operator)
        response = send(
            operator,
            "POST",
            "/api/admin/venue-inventory",
            {
                "event_slot_id": slot,
                "name": "합성 식당",
                "address": "가상 주소",
                "map_url": "javascript:alert(1)",
                "price_krw": 15000,
                "capacity": 6,
            },
        )
        assert response.status_code == 422


def test_unknown_food_is_an_exception_then_verified_inventory_allocates_once():
    import time
    from contextlib import ExitStack

    from serentable.gatherings import run_gathering_jobs
    from serentable.matching import run_due_matches
    from test_matching_runner import apply_and_pay, due_slot, prepare

    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for i, member in enumerate(members, 1):
            prepare(member, f"participant-0{i}")
        slot = due_slot(operator, close_in=4)
        for member in members:
            apply_and_pay(member, slot)
        created = send(
            operator,
            "POST",
            "/api/admin/venue-inventory",
            {
                "event_slot_id": slot,
                "name": "확인된 가상 식당",
                "address": "합성 주소",
                "map_url": "https://map.naver.com/",
                "price_krw": 15000,
                "capacity": 6,
            },
        )
        inventory = created.json()["inventory"]["id"]
        time.sleep(4.6)
        assert run_due_matches()[0]["seated_count"] == 4
        run_gathering_jobs()
        mine = members[0].get("/api/me/gatherings").json()["gatherings"][0]
        assert mine["venue_state"] == "PENDING_OPERATOR"
        assert mine["room_id"]
        assert len(members[0].get("/api/me/rooms").json()["rooms"]) == 1
        table = operator.get("/api/admin/gathering-tables").json()["tables"][0]
        payload = {
            "dining_table_id": table["id"],
            "food_snapshot": table["food_snapshot"],
            "confirmed_suitable": True,
        }
        stale = {**payload, "food_snapshot": "0" * 64}
        path = f"/api/admin/venue-inventory/{inventory}/food-approvals"
        assert send(operator, "POST", path, stale).status_code == 409
        assert send(operator, "POST", path, payload).status_code == 200
        run_gathering_jobs()
        run_gathering_jobs()
        mine = members[0].get("/api/me/gatherings").json()["gatherings"][0]
        assert mine["venue_state"] == "ASSIGNED"
        assert mine["venue"]["name"] == "확인된 가상 식당"
        messages = members[0].get(f"/api/me/rooms/{mine['room_id']}/messages").json()["messages"]
        assert len(messages) == 3  # confirmed, pending, assigned: no duplicate worker posts
        assert operator.get("/api/me/gatherings").status_code == 403
        assert members[0].get("/api/admin/gathering-tables").status_code == 403


def test_worker_reminders_start_content_and_rollback_are_atomic():
    import os
    import subprocess
    import sys
    import time
    from contextlib import ExitStack

    from serentable.database import database_engine
    from serentable.gatherings import run_gathering_jobs
    from serentable.matching import run_due_matches
    from sqlalchemy import text
    from test_applications import COMPLETE_PROFILE
    from test_matching_runner import apply_and_pay, due_slot, prepare

    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for i, member in enumerate(members, 1):
            prepare(member, f"participant-0{i}")
            assert (
                send(
                    member,
                    "PUT",
                    "/api/me/profile",
                    {
                        **COMPLETE_PROFILE,
                        "food_restrictions": {"status": "none"},
                        "allergies": {"status": "none"},
                    },
                ).status_code
                == 200
            )
        slot = due_slot(operator, close_in=4)
        for member in members:
            apply_and_pay(member, slot)
        assert (
            send(
                operator,
                "POST",
                "/api/admin/venue-inventory",
                {
                    "event_slot_id": slot,
                    "name": "합성 식당",
                    "address": "합성 주소",
                    "map_url": "https://map.naver.com/",
                    "price_krw": 15000,
                    "capacity": 6,
                },
            ).status_code
            == 201
        )
        time.sleep(4.6)
        assert run_due_matches()[0]["seated_count"] == 4
        # The approved storage-fault seam: DB rejects notification persistence.
        with database_engine().begin() as c:
            c.execute(
                text("""CREATE FUNCTION gathering_test_fail() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$""")
            )
            c.execute(
                text("""CREATE TRIGGER gathering_test_fault BEFORE INSERT ON app_notification
                FOR EACH ROW EXECUTE FUNCTION gathering_test_fail()""")
            )
        try:
            with pytest.raises(Exception):
                run_gathering_jobs()
            assert members[0].get("/api/me/rooms").json()["rooms"] == []
            assert members[0].get("/api/me/gatherings").json()["gatherings"][0]["venue"] is None
        finally:
            with database_engine().begin() as c:
                c.execute(text("DROP TRIGGER gathering_test_fault ON app_notification"))
                c.execute(text("DROP FUNCTION gathering_test_fail()"))
        # Fixture clock moves the isolated slot near its start; no production clock overrides.
        with database_engine().begin() as c:
            c.execute(
                text("""UPDATE event_slot SET closes_at=now()-interval '2 minutes',
                matches_at=now()-interval '1 minute', starts_at=now()+interval '30 minutes',
                ends_at=now()+interval '3 hours' WHERE id=:slot"""),
                {"slot": slot},
            )
        command = [sys.executable, "-m", "serentable.worker", "--once"]
        processes = [
            subprocess.Popen(
                command, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            for _ in range(2)
        ]
        for process in processes:
            output = process.communicate(timeout=30)
            assert process.returncode == 0, output
            assert b"worker_gathering_unavailable" not in output[1]
        gathering = members[0].get("/api/me/gatherings").json()["gatherings"][0]
        assert gathering["venue_state"] == "ASSIGNED"
        path = f"/api/me/rooms/{gathering['room_id']}/messages"
        messages = members[0].get(path).json()["messages"]
        assert len(messages) == 3  # confirmation + allocation + 24h reminder once
        with database_engine().begin() as c:
            c.execute(
                text("UPDATE event_slot SET starts_at=now()-interval '30 seconds' WHERE id=:id"),
                {"id": slot},
            )
        run_gathering_jobs()
        messages = members[0].get(path).json()["messages"]
        assert len(messages) == 4
        assert (
            "①" in messages[-1]["body"]
            and "②" in messages[-1]["body"]
            and "③" in messages[-1]["body"]
        )
        assert "독서" in messages[-1]["body"] and "아이스브레이킹" in messages[-1]["body"]
        run_gathering_jobs()
        assert len(members[0].get(path).json()["messages"]) == 4
        # Existing confirmation, payment and table remain intact throughout retries.
        mine = members[0].get("/api/me/applications").json()["applications"][0]
        assert mine["matching"]["state"] == "CONFIRMED"
