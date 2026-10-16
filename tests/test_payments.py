import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from serentable.main import app

# application_database is the autouse real-PostgreSQL setup shared with the application
# tests; its truncation cascades through applications to payments and entitlements.
from test_applications import (  # noqa: F401
    ORIGIN,
    SEOUL,
    application_database,
    apply,
    create_slot,
    login,
    make_ready,
    send,
)


def pay(client, application_id, product_code, key=None, simulate_failure=False):
    return send(
        client,
        "POST",
        f"/api/me/applications/{application_id}/payments",
        {
            "request_key": key or str(uuid.uuid4()),
            "product_code": product_code,
            "simulate_failure": simulate_failure,
        },
    )


def ready_application(operator, participant, login_id="participant-01", days=7):
    login(participant, login_id)
    make_ready(participant)
    slot = create_slot(operator, days=days)
    response = apply(participant, [slot])
    assert response.status_code == 201
    return response.json()["application"]


def test_catalog_lists_official_prices_and_marks_payment_as_mock():
    with TestClient(app) as participant:
        login(participant, "participant-01")
        response = participant.get("/api/products")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["mock"] is True
        assert [
            (item["code"], item["kind"], item["price_krw"], item["period_months"])
            for item in body["products"]
        ] == [
            ("single", "SINGLE", 9900, None),
            ("membership_1m", "MEMBERSHIP", 35000, 1),
            ("membership_3m", "MEMBERSHIP", 75000, 3),
            ("membership_6m", "MEMBERSHIP", 120000, 6),
        ]
        assert body["policy_version"] == "provisional-2026-10-16"


def test_single_pass_payment_snapshots_product_and_holds_pass_for_the_application():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        application = ready_application(operator, participant)
        assert application["payment_required"] is True
        assert application["payments"] == [] and application["coverage"] is None
        paid = pay(participant, application["id"], "single")
        assert paid.status_code == 201
        assert paid.headers["cache-control"] == "no-store"
        payment = paid.json()["payment"]
        assert payment["state"] == "PAID" and payment["mock"] is True
        assert payment["amount_krw"] == 9900
        assert payment["product"] == {
            "code": "single",
            "name": "1회권",
            "kind": "SINGLE",
            "version": "faq-2026-10-16",
            "price_krw": 9900,
            "period_months": None,
        }
        assert payment["policy_version"] == "provisional-2026-10-16"
        assert payment["completed_at"] is not None
        (listed,) = participant.get("/api/me/applications").json()["applications"]
        assert listed["payment_required"] is False
        assert listed["payments"] == [payment]
        entitlement = listed["coverage"]["entitlement"]
        assert listed["coverage"]["source"] == "payment"
        # Held for this application; consumed only at table confirmation (not built yet).
        assert entitlement["kind"] == "SINGLE" and entitlement["state"] == "HELD"
        assert entitlement["expires_at"] is None
        assert entitlement["application_id"] == application["id"]
        mine = participant.get("/api/me/entitlements")
        assert mine.status_code == 200 and mine.json()["entitlements"] == [entitlement]


def test_retried_payment_returns_same_result_and_paid_application_is_not_charged_again():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        application = ready_application(operator, participant)
        other = apply(participant, [create_slot(operator, days=8)]).json()["application"]
        key = str(uuid.uuid4())
        first = pay(participant, application["id"], "membership_3m", key)
        assert first.status_code == 201
        replay = pay(participant, application["id"], "membership_3m", key)
        assert (replay.status_code, replay.json()) == (200, first.json())
        for changed in (
            pay(participant, application["id"], "single", key),
            pay(participant, application["id"], "membership_3m", key, simulate_failure=True),
            pay(participant, other["id"], "membership_3m", key),
        ):
            assert (changed.status_code, changed.json()) == (
                409,
                {"detail": "request_key_reused"},
            )
        again = pay(participant, application["id"], "single")
        assert (again.status_code, again.json()) == (409, {"detail": "payment_already_paid"})
        assert len(participant.get("/api/me/entitlements").json()["entitlements"]) == 1


def test_simulated_failure_grants_nothing_and_a_new_attempt_keeps_the_failed_record():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        application = ready_application(operator, participant)
        key = str(uuid.uuid4())
        failed = pay(participant, application["id"], "single", key, simulate_failure=True)
        assert failed.status_code == 201
        failed_payment = failed.json()["payment"]
        assert failed_payment["state"] == "FAILED" and failed_payment["simulated_failure"]
        assert failed_payment["completed_at"] is not None
        # The same request after a failure is the same failed attempt, not a new charge.
        replay = pay(participant, application["id"], "single", key, simulate_failure=True)
        assert (replay.status_code, replay.json()) == (200, failed.json())
        (listed,) = participant.get("/api/me/applications").json()["applications"]
        assert listed["payment_required"] is True and listed["coverage"] is None
        assert participant.get("/api/me/entitlements").json()["entitlements"] == []
        retried = pay(participant, application["id"], "membership_1m")
        assert retried.status_code == 201 and retried.json()["payment"]["state"] == "PAID"
        (listed,) = participant.get("/api/me/applications").json()["applications"]
        assert [item["state"] for item in listed["payments"]] == ["PAID", "FAILED"]
        assert listed["payments"][1] == failed_payment
        assert listed["payment_required"] is False


def test_membership_runs_calendar_months_from_payment_and_covers_later_applications():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        application = ready_application(operator, participant, days=7)
        paid = pay(participant, application["id"], "membership_1m").json()["payment"]
        (membership,) = participant.get("/api/me/entitlements").json()["entitlements"]
        assert membership["kind"] == "MEMBERSHIP" and membership["state"] == "ACTIVE"
        assert membership["application_id"] is None
        assert membership["starts_at"] == paid["completed_at"]
        start = datetime.fromisoformat(membership["starts_at"]).astimezone(SEOUL)
        end = datetime.fromisoformat(membership["expires_at"]).astimezone(SEOUL)
        # One calendar month in Seoul: same wall-clock time, next month (or its last day).
        assert end.time() == start.time()
        assert (end.year * 12 + end.month) - (start.year * 12 + start.month) == 1
        assert end.day == start.day or (end.day < start.day and (end + timedelta(days=1)).day == 1)
        # A later application inside the period needs no new payment.
        inside = apply(participant, [create_slot(operator, days=20)]).json()["application"]
        assert inside["payment_required"] is False and inside["payments"] == []
        assert inside["coverage"] == {"source": "membership", "entitlement": membership}
        covered = pay(participant, inside["id"], "single")
        assert (covered.status_code, covered.json()) == (
            409,
            {"detail": "entitlement_already_covers"},
        )
        # A candidate after expiry is not covered; a too-short membership is refused.
        beyond = apply(participant, [create_slot(operator, days=40)]).json()["application"]
        assert beyond["payment_required"] is True and beyond["coverage"] is None
        short = pay(participant, beyond["id"], "membership_1m")
        assert (short.status_code, short.json()) == (409, {"detail": "membership_too_short"})
        assert pay(participant, beyond["id"], "membership_3m").status_code == 201
        assert len(participant.get("/api/me/entitlements").json()["entitlements"]) == 2


def test_concurrent_identical_payments_create_one_payment_and_one_entitlement():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        application = ready_application(operator, participant)
        other = apply(participant, [create_slot(operator, days=8)]).json()["application"]
        token = participant.get("/api/auth/csrf").json()["csrf_token"]
        headers = {"Origin": ORIGIN, "X-CSRF-Token": token}

        def submit(target_and_body):
            target, body = target_and_body
            return participant.post(
                f"/api/me/applications/{target}/payments", json=body, headers=headers
            )

        same = {"request_key": str(uuid.uuid4()), "product_code": "membership_6m"}
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(submit, [(application["id"], same)] * 6))
        assert sorted(r.status_code for r in responses) == [200] * 5 + [201]
        assert len({r.json()["payment"]["id"] for r in responses}) == 1
        # Distinct keys for one unpaid application: one charge, the rest are refused.
        distinct = [
            (other["id"], {"request_key": str(uuid.uuid4()), "product_code": "single"})
            for _ in range(6)
        ]
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(submit, distinct))
        codes = sorted(r.status_code for r in responses)
        # The 6-month membership already covers the other application.
        assert codes == [409] * 6
        assert {r.json()["detail"] for r in responses} == {"entitlement_already_covers"}
        assert len(participant.get("/api/me/entitlements").json()["entitlements"]) == 1


def test_concurrent_distinct_attempts_for_one_application_charge_once():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        application = ready_application(operator, participant)
        token = participant.get("/api/auth/csrf").json()["csrf_token"]
        headers = {"Origin": ORIGIN, "X-CSRF-Token": token}

        def submit(body):
            return participant.post(
                f"/api/me/applications/{application['id']}/payments", json=body, headers=headers
            )

        bodies = [{"request_key": str(uuid.uuid4()), "product_code": "single"} for _ in range(6)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(submit, bodies))
        assert sorted(r.status_code for r in responses) == [201] + [409] * 5
        (listed,) = participant.get("/api/me/applications").json()["applications"]
        assert [item["state"] for item in listed["payments"]] == ["PAID"]
        assert len(participant.get("/api/me/entitlements").json()["entitlements"]) == 1


def test_payment_rejects_foreign_canceled_or_malformed_requests_and_enforces_roles():
    with (
        TestClient(app) as anonymous,
        TestClient(app) as operator,
        TestClient(app) as one,
        TestClient(app) as two,
    ):
        login(operator, "operator")
        application = ready_application(operator, one)
        login(two, "participant-02")
        foreign = pay(two, application["id"], "single")
        assert (foreign.status_code, foreign.json()) == (404, {"detail": "application_not_found"})
        assert pay(one, str(uuid.uuid4()), "single").status_code == 404
        path = f"/api/me/applications/{application['id']}/payments"
        for payload in (
            {"request_key": str(uuid.uuid4()), "product_code": "three_pass"},
            {"request_key": "not-a-uuid", "product_code": "single"},
            {"product_code": "single"},
            {"request_key": str(uuid.uuid4()), "product_code": "single", "amount_krw": 0},
        ):
            assert send(one, "POST", path, payload).status_code == 422, payload
        assert pay(operator, application["id"], "single").status_code == 403
        assert pay(anonymous, application["id"], "single").status_code == 401
        assert one.post(path, json={"product_code": "single"}).status_code == 403
        assert anonymous.get("/api/me/entitlements").status_code == 401
        assert operator.get("/api/me/entitlements").status_code == 403
        assert anonymous.get("/api/products").status_code == 401
        send(one, "POST", f"/api/me/applications/{application['id']}/cancel")
        canceled = pay(one, application["id"], "single")
        assert (canceled.status_code, canceled.json()) == (
            409,
            {"detail": "application_not_payable"},
        )
        (listed,) = one.get("/api/me/applications").json()["applications"]
        assert listed["payments"] == [] and listed["payment_required"] is False


def test_operator_sees_payment_state_read_only_and_canceling_keeps_the_payment():
    with TestClient(app) as operator, TestClient(app) as one, TestClient(app) as two:
        login(operator, "operator")
        paid = ready_application(operator, one)
        pay(one, paid["id"], "single")
        failed = ready_application(operator, two, login_id="participant-02", days=8)
        pay(two, failed["id"], "single", simulate_failure=True)
        rows = {
            row["participant"]["login_id"]: row
            for row in operator.get("/api/admin/applications").json()["applications"]
        }
        assert rows["participant-01"]["payments"][0]["state"] == "PAID"
        assert rows["participant-02"]["payments"][0]["state"] == "FAILED"
        assert rows["participant-02"]["payment_required"] is True
        # Canceling is not a refund (U04): the payment and held pass remain as recorded.
        send(one, "POST", f"/api/me/applications/{paid['id']}/cancel")
        (listed,) = one.get("/api/me/applications").json()["applications"]
        assert listed["state"] == "CANCELED" and listed["payments"][0]["state"] == "PAID"
        assert one.get("/api/me/entitlements").json()["entitlements"][0]["state"] == "HELD"
