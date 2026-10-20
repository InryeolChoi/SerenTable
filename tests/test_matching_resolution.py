"""Participant failure choices at the HTTP / actual PostgreSQL worker boundary."""

import time
import uuid
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from serentable.main import app
from serentable.matching import run_slot_matching
from support import login, send
from test_applications import apply, create_slot
from test_matching_runner import (  # noqa: F401
    apply_and_pay,
    due_slot,
    matching_database,
    prepare,
)


def failure(owner, operator, product="single"):
    from test_payments import pay

    slot = due_slot(operator, close_in=1.0)
    application = apply(owner, [slot]).json()["application"]
    assert pay(owner, application["id"], product).status_code == 201
    time.sleep(1.6)
    assert run_slot_matching(slot)["seated_count"] == 0
    return application["id"]


def choose(owner, application, action, target=None, key=None, run_id=None):
    if run_id is None:
        run_id = owner.get(f"/api/me/applications/{application}/alternatives").json()[
            "failure_run_id"
        ]
    return send(
        owner,
        "POST",
        f"/api/me/applications/{application}/resolutions",
        {
            "request_key": key or str(uuid.uuid4()),
            "failure_run_id": run_id,
            "action": action,
            "event_slot_id": target,
        },
    )


def test_alternative_selection_keeps_payment_and_reaches_worker_confirmation():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for i, member in enumerate(members, 1):
            prepare(member, f"participant-0{i}")
        owner = members[0]
        application = failure(owner, operator)
        before = owner.get("/api/me/applications").json()["applications"][0]
        target = due_slot(operator, region="gangnam", days=9, close_in=3.0)
        key = str(uuid.uuid4())
        # Baseline RED: the old lookup has no resolution token and POST does not exist.
        run_id = owner.get(f"/api/me/applications/{application}/alternatives").json().get(
            "failure_run_id"
        ) or str(uuid.uuid4())
        response = choose(owner, application, "TRANSFER", target, key, run_id)
        assert response.status_code == 200, response.text
        assert response.json()["resolution"]["action"] == "TRANSFER"
        assert choose(owner, application, "TRANSFER", target, key, run_id).json() == response.json()
        mine = owner.get("/api/me/applications").json()["applications"][0]
        assert mine["id"] == application
        assert mine["payments"] == before["payments"]
        assert mine["matching"]["state"] == "WAITING"
        assert mine["resolutions"][0]["state"] == "TRANSFERRED"
        assert mine["matching_eligible_slot_ids"] == [target]
        for member in members[1:]:
            apply_and_pay(member, target)
        time.sleep(3.6)
        assert run_slot_matching(target)["seated_count"] == 4
        history = operator.get("/api/admin/match-runs").json()["match_runs"]
        confirmed_run = next(r for r in history if r["event_slot"]["id"] == target)
        moved = next(m for m in confirmed_run["members"] if m["application_id"] == application)
        assert moved["explanation"]["transfer_count"] == 1
        mine = owner.get("/api/me/applications").json()["applications"][0]
        assert mine["matching"]["state"] == "CONFIRMED"
        assert owner.get("/api/me/entitlements").json()["entitlements"][0]["state"] == "USED"


def test_hold_and_reuse_never_rewrite_purchase_and_need_no_new_payment():
    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        original = failure(owner, operator)
        (right,) = owner.get("/api/me/entitlements").json()["entitlements"]
        held = choose(owner, original, "HOLD")
        assert held.status_code == 200, held.text
        (stored,) = owner.get("/api/me/entitlements").json()["entitlements"]
        assert stored["reusable"] is True
        assert stored["application_id"] == original
        assert stored["reserved_application_id"] is None
        target = create_slot(operator, days=12)
        new = apply(owner, [target]).json()["application"]["id"]
        path = f"/api/me/entitlements/{right['id']}/reuse"
        payload = {"application_id": new, "request_key": str(uuid.uuid4())}
        attached = send(owner, "POST", path, payload)
        assert attached.status_code == 200, attached.text
        assert send(owner, "POST", path, payload).json() == attached.json()
        mine = {a["id"]: a for a in owner.get("/api/me/applications").json()["applications"]}
        assert mine[new]["payments"] == []
        assert mine[new]["payment_required"] is False
        assert mine[new]["matching_eligible_slot_ids"] == [target]
        assert mine[original]["matching_eligible_slot_ids"] == []
        assert mine[new]["coverage"]["entitlement"]["application_id"] == original
        assert mine[new]["coverage"]["entitlement"]["reserved_application_id"] == new
        assert (
            send(owner, "POST", path, {**payload, "request_key": str(uuid.uuid4())}).status_code
            == 409
        )


def test_system_failure_refund_is_full_mock_and_repeat_safe():
    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        key = str(uuid.uuid4())
        offer = owner.get(f"/api/me/applications/{application}/alternatives").json()
        assert offer["refund_state"] == "REFUND_AVAILABLE"
        (available,) = owner.get("/api/me/applications").json()["applications"]
        assert available["refund_state"] == "REFUND_AVAILABLE"
        (admin_available,) = operator.get("/api/admin/applications").json()["applications"]
        assert admin_available["refund_state"] == "REFUND_AVAILABLE"
        run_id = offer["failure_run_id"]
        refunded = choose(owner, application, "REFUND", key=key, run_id=run_id)
        assert refunded.status_code == 200, refunded.text
        assert (
            choose(owner, application, "REFUND", key=key, run_id=run_id).json() == refunded.json()
        )
        assert choose(owner, application, "HOLD", key=key, run_id=run_id).status_code == 409
        (mine,) = owner.get("/api/me/applications").json()["applications"]
        assert mine["payments"][0]["state"] == "REFUNDED"
        assert [e["state"] for e in mine["resolutions"][0]["refund_events"]] == [
            "REFUND_REQUESTED",
            "REFUND_PROCESSING",
            "REFUNDED",
        ]
        assert all(e["amount_krw"] == 9900 for e in mine["resolutions"][0]["refund_events"])
        assert mine["payments"][0]["amount_krw"] == 9900
        (admin,) = operator.get("/api/admin/applications").json()["applications"]
        assert admin["resolutions"] == mine["resolutions"]
        assert mine["coverage"] is None
        assert mine["payment_required"] is False
        assert mine["matching_eligible_slot_ids"] == []
        (right,) = owner.get("/api/me/entitlements").json()["entitlements"]
        assert right["state"] == "REFUNDED" and not right["reusable"]
        assert choose(owner, application, "HOLD", run_id=run_id).status_code == 409


def test_membership_extends_once_at_final_failure_and_cash_refund_is_deferred():
    from datetime import datetime, timedelta

    from test_payments import pay

    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        source = due_slot(operator, close_in=1.0)
        application = apply(owner, [source]).json()["application"]["id"]
        assert pay(owner, application, "membership_1m").status_code == 201
        before = owner.get("/api/me/entitlements").json()["entitlements"][0]["expires_at"]
        time.sleep(1.6)
        run_slot_matching(source)
        after = owner.get("/api/me/entitlements").json()["entitlements"][0]["expires_at"]
        assert datetime.fromisoformat(after) - datetime.fromisoformat(before) == timedelta(days=7)
        assert choose(owner, application, "REFUND").json() == {
            "detail": "membership_refund_deferred"
        }
        target = due_slot(operator, region="gangnam", days=14, close_in=1.0)
        assert choose(owner, application, "TRANSFER", target).status_code == 200
        time.sleep(1.6)
        run_slot_matching(target)
        assert owner.get("/api/me/entitlements").json()["entitlements"][0]["expires_at"] == after
        assert choose(owner, application, "HOLD").status_code == 200


def test_alternatives_exclude_slots_outside_membership_and_keep_original_pending():
    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator, "membership_1m")
        inside = create_slot(operator, days=12)
        outside = create_slot(operator, days=60)
        offered = owner.get(f"/api/me/applications/{application}/alternatives")
        ids = [s["id"] for s in offered.json()["alternatives"]]
        assert inside in ids and outside not in ids
        assert choose(owner, application, "TRANSFER", outside).status_code == 409
        assert choose(owner, application, "TRANSFER", inside).status_code == 200


def test_pending_candidate_blocks_resolution_and_membership_extension():
    from test_payments import pay

    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        first = due_slot(operator, close_in=1.0)
        pending = create_slot(operator, days=14)
        application = apply(owner, [first, pending]).json()["application"]["id"]
        assert pay(owner, application, "membership_1m").status_code == 201
        before = owner.get("/api/me/entitlements").json()
        time.sleep(1.6)
        run_slot_matching(first)
        assert owner.get("/api/me/entitlements").json() == before
        assert choose(owner, application, "HOLD").status_code == 409
        assert (
            choose(owner, application, "TRANSFER", create_slot(operator, days=16)).status_code
            == 409
        )


def test_invalid_target_stale_failure_and_privileges_cannot_change_application():
    with TestClient(app) as operator, TestClient(app) as owner, TestClient(app) as other:
        login(operator, "operator")
        prepare(owner, "participant-01")
        login(other, "participant-02")
        application = failure(owner, operator)
        target = create_slot(operator, days=14)
        run_id = owner.get(f"/api/me/applications/{application}/alternatives").json()[
            "failure_run_id"
        ]
        before = owner.get("/api/me/applications").json()
        assert (
            choose(owner, application, "TRANSFER", str(uuid.uuid4()), run_id=run_id).status_code
            == 409
        )
        assert (
            choose(owner, application, "TRANSFER", target, run_id=str(uuid.uuid4())).status_code
            == 409
        )
        assert choose(owner, application, "TRANSFER", None, run_id=run_id).status_code == 422
        path = f"/api/me/applications/{application}/resolutions"
        payload = {"request_key": str(uuid.uuid4()), "failure_run_id": run_id, "action": "HOLD"}
        assert send(other, "POST", path, payload).status_code == 404
        assert send(operator, "POST", path, payload).status_code == 403
        assert owner.post(path, json=payload).status_code == 403
        with TestClient(app) as anonymous:
            assert send(anonymous, "POST", path, payload).status_code == 401
        assert owner.get("/api/me/applications").json() == before
        duplicate = apply(owner, [target]).json()["application"]["id"]
        assert choose(owner, application, "TRANSFER", target, run_id=run_id).status_code == 409
        assert duplicate != application


def test_two_simultaneous_choices_have_one_winner_and_identical_replays_are_stable():
    from concurrent.futures import ThreadPoolExecutor

    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        run_id = owner.get(f"/api/me/applications/{application}/alternatives").json()[
            "failure_run_id"
        ]
        target = create_slot(operator, days=14)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(choose, owner, application, action, slot, None, run_id)
                for action, slot in [("TRANSFER", target), ("REFUND", None)]
            ]
            results = [future.result(timeout=15) for future in futures]
        assert sorted(r.status_code for r in results) == [200, 409]
        (mine,) = owner.get("/api/me/applications").json()["applications"]
        if results[0].status_code == 200:
            assert mine["matching_eligible_slot_ids"] == [target]
            assert mine["payments"][0]["state"] == "PAID"
        else:
            assert mine["matching_eligible_slot_ids"] == []
            assert mine["payments"][0]["state"] == "REFUNDED"


@pytest.mark.parametrize("action", ["TRANSFER", "HOLD", "REFUND"])
def test_resolution_rolls_back_every_change_after_database_failure(action):
    from serentable.database import database_engine
    from sqlalchemy import text

    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        target = create_slot(operator, days=14)
        run_id = owner.get(f"/api/me/applications/{application}/alternatives").json()[
            "failure_run_id"
        ]
        before = owner.get("/api/me/applications").json()
        rights = owner.get("/api/me/entitlements").json()
        with database_engine().begin() as connection:
            connection.execute(
                text("""CREATE FUNCTION resolution_test_fault() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic failure'; END $$""")
            )
            connection.execute(
                text("""CREATE TRIGGER resolution_test_fault BEFORE UPDATE ON match_participation
                FOR EACH ROW EXECUTE FUNCTION resolution_test_fault()""")
            )
        key = str(uuid.uuid4())
        try:
            assert (
                choose(
                    owner,
                    application,
                    action,
                    target if action == "TRANSFER" else None,
                    key,
                    run_id,
                ).status_code
                == 503
            )
            assert owner.get("/api/me/applications").json() == before
            assert owner.get("/api/me/entitlements").json() == rights
        finally:
            with database_engine().begin() as connection:
                connection.execute(
                    text("DROP TRIGGER resolution_test_fault ON match_participation")
                )
                connection.execute(text("DROP FUNCTION resolution_test_fault()"))
        assert (
            choose(
                owner, application, action, target if action == "TRANSFER" else None, key, run_id
            ).status_code
            == 200
        )


def test_transfer_preserves_original_submission_replay():
    from test_payments import pay

    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        source = due_slot(operator, close_in=1.0)
        payload = {"request_key": str(uuid.uuid4()), "event_slot_ids": [source]}
        application = send(owner, "POST", "/api/me/applications", payload).json()["application"][
            "id"
        ]
        assert pay(owner, application, "single").status_code == 201
        time.sleep(1.6)
        run_slot_matching(source)
        assert (
            choose(owner, application, "TRANSFER", create_slot(operator, days=15)).status_code
            == 200
        )
        replay = send(owner, "POST", "/api/me/applications", payload)
        assert replay.status_code == 200, replay.text
        assert replay.json()["application"]["id"] == application


def test_different_workers_cannot_confirm_overlapping_applications_for_one_user():
    from concurrent.futures import ThreadPoolExecutor

    from serentable.database import database_engine
    from sqlalchemy import text

    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        owners = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for i, owner in enumerate(owners, 1):
            prepare(owner, f"participant-0{i}")
        first = due_slot(operator, close_in=3.0)
        second = due_slot(operator, region="gangnam", close_in=3.0)
        for owner in owners:
            apply_and_pay(owner, first)
            apply_and_pay(owner, second)
        time.sleep(3.6)
        # Widen the real race before persistence; the shared transaction lock must still
        # prevent the other worker from validating against the same old snapshot.
        with database_engine().begin() as connection:
            connection.execute(
                text("""CREATE FUNCTION resolution_slow_assignment() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(0.15); RETURN NEW; END $$""")
            )
            connection.execute(
                text("""CREATE TRIGGER resolution_slow_assignment BEFORE INSERT ON table_assignment
                FOR EACH ROW EXECUTE FUNCTION resolution_slow_assignment()""")
            )
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [pool.submit(run_slot_matching, slot) for slot in [first, second]]
                results = [job.result(timeout=20) for job in jobs]
            assert sorted(r["seated_count"] for r in results) == [0, 4]
            for owner in owners:
                mine = owner.get("/api/me/applications").json()["applications"]
                assert sum(a["matching"]["state"] == "CONFIRMED" for a in mine) == 1
        finally:
            with database_engine().begin() as connection:
                connection.execute(
                    text("DROP TRIGGER resolution_slow_assignment ON table_assignment")
                )
                connection.execute(text("DROP FUNCTION resolution_slow_assignment()"))


def test_time_overlap_target_and_confirmed_application_are_protected():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        owners = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for i, owner in enumerate(owners, 1):
            prepare(owner, f"participant-0{i}")
        slot = due_slot(operator, close_in=3.0)
        confirmed = [apply_and_pay(owner, slot) for owner in owners]
        time.sleep(3.6)
        assert run_slot_matching(slot)["seated_count"] == 4
        owner = owners[0]
        preserved = owner.get("/api/me/applications").json()["applications"][0]
        # A separate non-overlapping failure, still eligible for a resolution.
        failed = due_slot(operator, region="gangnam", days=14, close_in=1.0)
        application = apply_and_pay(owner, failed)
        time.sleep(1.6)
        run_slot_matching(failed)
        overlap = create_slot(operator, region="jamsil", days=7)
        offered = owner.get(f"/api/me/applications/{application}/alternatives").json()
        assert overlap not in [s["id"] for s in offered["alternatives"]]
        assert choose(owner, application, "TRANSFER", overlap).status_code == 409
        assert (
            choose(owner, confirmed[0], "HOLD", run_id=offered["failure_run_id"]).status_code == 409
        )
        after = {a["id"]: a for a in owner.get("/api/me/applications").json()["applications"]}
        assert after[confirmed[0]] == preserved


def test_identical_concurrent_resolution_requests_return_one_stable_result():
    from concurrent.futures import ThreadPoolExecutor

    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        application = failure(owner, operator)
        run_id = owner.get(f"/api/me/applications/{application}/alternatives").json()[
            "failure_run_id"
        ]
        key = str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [
                pool.submit(choose, owner, application, "HOLD", None, key, run_id) for _ in range(2)
            ]
            results = [job.result(timeout=15) for job in jobs]
        assert [r.status_code for r in results] == [200, 200]
        assert results[0].json() == results[1].json()
        (mine,) = owner.get("/api/me/applications").json()["applications"]
        assert len(mine["resolutions"]) == 1


def test_a_held_pass_cannot_be_reserved_for_two_new_applications_concurrently():
    from concurrent.futures import ThreadPoolExecutor

    with TestClient(app) as operator, TestClient(app) as owner:
        login(operator, "operator")
        prepare(owner, "participant-01")
        source = failure(owner, operator)
        assert choose(owner, source, "HOLD").status_code == 200
        (right,) = owner.get("/api/me/entitlements").json()["entitlements"]
        new = [
            apply(owner, [create_slot(operator, days=day)]).json()["application"]["id"]
            for day in [14, 15]
        ]
        path = f"/api/me/entitlements/{right['id']}/reuse"
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [
                pool.submit(
                    send,
                    owner,
                    "POST",
                    path,
                    {"application_id": a, "request_key": str(uuid.uuid4())},
                )
                for a in new
            ]
            results = [job.result(timeout=15) for job in jobs]
        assert sorted(r.status_code for r in results) == [200, 409]
        mine = owner.get("/api/me/applications").json()["applications"]
        assert sum(a["coverage"] is not None for a in mine if a["id"] in new) == 1


def test_existing_consented_candidate_continues_automatically_after_first_failure():
    from test_payments import pay

    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        owners = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for i, owner in enumerate(owners, 1):
            prepare(owner, f"participant-0{i}")
        first = due_slot(operator, close_in=3.0)
        later = due_slot(operator, region="gangnam", days=14, close_in=5.0)
        original = apply(owners[0], [first, later]).json()["application"]["id"]
        assert pay(owners[0], original, "single").status_code == 201
        for owner in owners[1:]:
            apply_and_pay(owner, later)
        time.sleep(3.6)
        assert run_slot_matching(first)["seated_count"] == 0
        assert choose(owners[0], original, "HOLD").status_code == 409
        time.sleep(2.0)
        assert run_slot_matching(later)["seated_count"] == 4
        (mine,) = owners[0].get("/api/me/applications").json()["applications"]
        assert mine["id"] == original and mine["matching"]["state"] == "CONFIRMED"
        assert len(mine["payments"]) == 1
