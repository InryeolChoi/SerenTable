"""Approved A3: keep reservations; require current-condition review through the API."""

import time
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from serentable.gatherings import run_gathering_jobs
from serentable.main import app
from serentable.matching import run_due_matches
from support import login, send
from test_applications import COMPLETE_PROFILE
from test_matching_runner import apply_and_pay, due_slot, prepare

CLEAR = {
    **COMPLETE_PROFILE,
    "food_restrictions": {"status": "none"},
    "allergies": {"status": "none"},
}


def allocation(stack):
    operator = stack.enter_context(TestClient(app))
    members = [stack.enter_context(TestClient(app)) for _ in range(4)]
    login(operator, "operator")
    for i, member in enumerate(members, 1):
        prepare(member, f"participant-0{i}")
        assert send(member, "PUT", "/api/me/profile", CLEAR).status_code == 200
    slot = due_slot(operator, close_in=4)
    for member in members:
        apply_and_pay(member, slot)
    inventory = send(
        operator,
        "POST",
        "/api/admin/venue-inventory",
        {
            "event_slot_id": slot,
            "name": "합성 확인 식당",
            "address": "합성 주소",
            "map_url": "https://map.naver.com/",
            "price_krw": 15000,
            "capacity": 6,
        },
    ).json()["inventory"]
    time.sleep(4.6)
    assert run_due_matches()[0]["seated_count"] == 4
    run_gathering_jobs()
    gathering = members[0].get("/api/me/gatherings").json()["gatherings"][0]
    return operator, members, inventory, gathering


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("allergies", {"status": "specified", "details": "합성 알레르기"}),
        ("food_restrictions", {"status": "specified", "details": "합성 음식 제한"}),
        ("meal_budget_bands", ["10000_20000", "20000_30000"]),
    ],
)
def test_changed_conditions_require_current_review_without_changing_reservation(
    seeded_database, field, value
):
    with ExitStack() as stack:
        operator, members, inventory, gathering = allocation(stack)
        original = operator.get("/api/admin/gathering-tables").json()["tables"][0]
        changed = {**CLEAR, field: value}
        assert send(members[0], "PUT", "/api/me/profile", changed).status_code == 200
        run_gathering_jobs()
        run_gathering_jobs()
        items = operator.get("/api/admin/exceptions").json()["exceptions"]
        review = [e for e in items if e["category"] == "VENUE_CONDITIONS"]
        assert len(review) == 1
        item = review[0]
        assert item["resolvable"] is False
        assert (
            send(
                operator,
                "POST",
                f"/api/admin/exceptions/gathering/{item['id']}/resolve",
                {"note": "메모만"},
            ).status_code
            == 409
        )
        current = operator.get("/api/admin/gathering-tables").json()["tables"][0]
        path = f"/api/admin/venue-inventory/{inventory['id']}/food-approvals"
        payload = {
            "dining_table_id": current["id"],
            "food_snapshot": current["food_snapshot"],
            "confirmed_suitable": True,
        }
        assert (
            send(
                operator, "POST", path, {**payload, "food_snapshot": original["food_snapshot"]}
            ).status_code
            == 409
        )
        assert send(members[0], "POST", path, payload).status_code == 403
        assert operator.post(path, json=payload).status_code == 403
        assert send(operator, "POST", path, payload).status_code == 200
        assert send(operator, "POST", path, payload).status_code == 200
        run_gathering_jobs()
        assert not any(
            e["category"] == "VENUE_CONDITIONS"
            for e in operator.get("/api/admin/exceptions?state=OPEN").json()["exceptions"]
        )
        assert members[0].get("/api/me/gatherings").json()["gatherings"][0] == gathering
        # Another change after review reopens the same exception without duplicating it.
        assert send(members[0], "PUT", "/api/me/profile", CLEAR).status_code == 200
        run_gathering_jobs()
        reopened = [
            e
            for e in operator.get("/api/admin/exceptions?state=OPEN").json()["exceptions"]
            if e["category"] == "VENUE_CONDITIONS"
        ]
        assert [e["id"] for e in reopened] == [item["id"]]


def test_legacy_baseline_wrong_inventory_and_price_mismatch_require_review(seeded_database):
    from serentable.database import database_engine
    from sqlalchemy import text

    with ExitStack() as stack:
        operator, members, inventory, gathering = allocation(stack)
        with database_engine().begin() as connection:
            connection.execute(
                text("UPDATE venue_allocation SET reviewed_conditions_snapshot=NULL")
            )
        run_gathering_jobs()
        (item,) = operator.get("/api/admin/exceptions?state=OPEN").json()["exceptions"]
        assert item["reason_code"] == "condition_baseline_missing"
        other = send(
            operator,
            "POST",
            "/api/admin/venue-inventory",
            {
                **{
                    key: inventory[key]
                    for key in (
                        "event_slot_id",
                        "name",
                        "address",
                        "map_url",
                        "price_krw",
                        "capacity",
                    )
                },
                "name": "다른 합성 식당",
            },
        ).json()["inventory"]
        current = operator.get("/api/admin/gathering-tables").json()["tables"][0]
        payload = {
            "dining_table_id": current["id"],
            "food_snapshot": current["food_snapshot"],
            "confirmed_suitable": True,
        }
        assert (
            send(
                operator,
                "POST",
                f"/api/admin/venue-inventory/{other['id']}/food-approvals",
                payload,
            ).status_code
            == 409
        )
        assert (
            send(
                members[0],
                "PUT",
                "/api/me/profile",
                {**CLEAR, "meal_budget_bands": ["20000_30000"]},
            ).status_code
            == 200
        )
        current = operator.get("/api/admin/gathering-tables").json()["tables"][0]
        payload["food_snapshot"] = current["food_snapshot"]
        path = f"/api/admin/venue-inventory/{inventory['id']}/food-approvals"
        assert send(operator, "POST", path, payload).json()["detail"] == "venue_budget_mismatch"
        assert len(operator.get("/api/admin/exceptions?state=OPEN").json()["exceptions"]) == 1
        assert members[0].get("/api/me/gatherings").json()["gatherings"][0] == gathering
        assert send(members[0], "PUT", "/api/me/profile", CLEAR).status_code == 200
        current = operator.get("/api/admin/gathering-tables").json()["tables"][0]
        payload["food_snapshot"] = current["food_snapshot"]
        assert send(operator, "POST", path, payload).status_code == 200
        assert operator.get("/api/admin/exceptions?state=OPEN").json()["exceptions"] == []


def test_profile_update_during_review_commits_then_requires_new_review(seeded_database):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from serentable.database import database_engine
    from sqlalchemy import event

    with ExitStack() as stack:
        operator, members, inventory, gathering = allocation(stack)
        assert (
            send(
                members[0],
                "PUT",
                "/api/me/profile",
                {**CLEAR, "allergies": {"status": "specified", "details": "합성 조건 A"}},
            ).status_code
            == 200
        )
        run_gathering_jobs()
        current = operator.get("/api/admin/gathering-tables").json()["tables"][0]
        payload = {
            "dining_table_id": current["id"],
            "food_snapshot": current["food_snapshot"],
            "confirmed_suitable": True,
        }
        profile_locked, user_locked = threading.Event(), threading.Event()
        engine = database_engine()

        def after_sql(connection, cursor, statement, params, context, many):
            if "FOR SHARE OF p" in statement and threading.current_thread().name == "review":
                profile_locked.set()
                assert user_locked.wait(10)
            if "SELECT id FROM app_user WHERE id=" in statement and profile_locked.is_set():
                user_locked.set()

        def review():
            threading.current_thread().name = "review"
            return send(
                operator,
                "POST",
                f"/api/admin/venue-inventory/{inventory['id']}/food-approvals",
                payload,
            )

        event.listen(engine, "after_cursor_execute", after_sql)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(review)
                assert profile_locked.wait(10)
                changed = send(
                    members[0],
                    "PUT",
                    "/api/me/profile",
                    {**CLEAR, "allergies": {"status": "specified", "details": "합성 조건 B"}},
                )
                assert pending.result(timeout=15).status_code == 200
                assert changed.status_code == 200
        finally:
            event.remove(engine, "after_cursor_execute", after_sql)
        run_gathering_jobs()
        (item,) = operator.get("/api/admin/exceptions?state=OPEN").json()["exceptions"]
        assert item["category"] == "VENUE_CONDITIONS"
        assert members[0].get("/api/me/gatherings").json()["gatherings"][0] == gathering
        audit = operator.get("/api/admin/audit").text
        assert "합성 조건" not in audit
