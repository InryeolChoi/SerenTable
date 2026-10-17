"""Exercise public HTTPS with synthetic accounts, without exporting credentials.

Run inside the deployed API container. Requires DEPLOY_EXPECT_VERSION and the two
DEMO_*_PASSWORD environment variables. Creates one slot and a synthetic application,
simulates a failed and a successful payment, then cancels the application. Mock payment
history and its held pass remain intentionally; no refund policy is invented.
Only fixed PASS/FAIL labels are printed, never responses, cookies or credentials.
"""

import json
import os
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


class Response:
    def __init__(self, response):
        self.status_code = response.code
        self.headers = response.headers
        self.body = response.read()

    def json(self):
        return json.loads(self.body)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http_request_failed")


class Client:
    """Cookie-aware HTTPS client without additional production dependencies."""

    def __init__(self, base_url, timeout=25):
        self.base_url, self.timeout = base_url, timeout
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(self, method, path, payload=None, headers=None):
        body = None if payload is None else json.dumps(payload).encode()
        request = Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return Response(response)
        except HTTPError as response:
            with response:
                return Response(response)

    def get(self, path):
        return self.request("GET", path)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def check(name, condition):
    if not condition:
        print("FAIL " + name, flush=True)
        raise AssertionError(name)
    print("PASS " + name, flush=True)


def change(client, method, path, payload=None):
    token = client.get("/api/auth/csrf")
    token.raise_for_status()
    return client.request(
        method,
        path,
        payload=payload,
        headers={
            "Origin": str(client.base_url).rstrip("/"),
            "X-CSRF-Token": token.json()["csrf_token"],
        },
    )


def login(client, account, password):
    response = change(
        client, "POST", "/api/auth/login", {"login_id": account, "password": password}
    )
    check(account + "_login", response.status_code == 200)
    check(account + "_no_store", response.headers.get("cache-control") == "no-store")


def main():
    origin = os.environ.get("DEPLOY_ORIGIN", os.environ.get("APP_ORIGIN", "")).rstrip("/")
    expected = os.environ["DEPLOY_EXPECT_VERSION"]
    check("https_target", origin.startswith("https://") and len(expected) == 40)
    with (
        Client(base_url=origin, timeout=25) as operator,
        Client(base_url=origin, timeout=25) as participant,
    ):
        check(
            "expected_deployed_version", operator.get("/api/health").json()["version"] == expected
        )
        login(operator, "operator", os.environ["DEMO_OPERATOR_PASSWORD"])
        login(participant, "participant-04", os.environ["DEMO_PARTICIPANT_PASSWORD"])
        check(
            "participant_admin_denied",
            participant.get("/api/admin/applications").status_code == 403,
        )
        current = participant.get("/api/me/profile").json()
        if not current["complete"]:
            defaults = {
                "name": "합성 검증",
                "display_name": "배포 확인 참가자",
                "contact": "010-0000-0000",
                "instagram_id": "synthetic_deploy_check",
                "birth_year": 1995,
                "gender": "합성",
                "occupation": "합성 검증",
                "interests": ["music"],
                "self_traits": ["listener"],
                "desired_traits": ["similar"],
                "meal_budget_bands": ["20000_30000"],
            }
            profile = current["profile"] or {}
            for key, value in defaults.items():
                if not profile.get(key):
                    profile[key] = value
            saved = change(participant, "PUT", "/api/me/profile", profile)
            check(
                "synthetic_profile_complete", saved.status_code == 200 and saved.json()["complete"]
            )
        policies = participant.get("/api/consent/policies").json()["policies"]
        if not participant.get("/api/me/consents").json()["complete"]:
            accepted = change(
                participant,
                "PUT",
                "/api/me/consents",
                {
                    "consents": [
                        {"purpose": p["purpose"], "version": p["version"], "accepted": True}
                        for p in policies
                        if p["required"]
                    ]
                },
            )
            check(
                "synthetic_consent_complete",
                accepted.status_code == 200 and accepted.json()["complete"],
            )
        now = datetime.now(timezone.utc)
        starts = now + timedelta(days=7)
        for entitlement in participant.get("/api/me/entitlements").json()["entitlements"]:
            if entitlement["kind"] == "MEMBERSHIP":
                starts = max(
                    starts, datetime.fromisoformat(entitlement["expires_at"]) + timedelta(days=7)
                )
        starts += timedelta(seconds=secrets.randbelow(3600))
        slot = change(
            operator,
            "POST",
            "/api/admin/event-slots",
            {
                "region_code": "hongdae",
                "starts_at": starts.isoformat(),
                "ends_at": (starts + timedelta(hours=2)).isoformat(),
                "closes_at": (now + timedelta(minutes=20)).isoformat(),
                "matches_at": (now + timedelta(minutes=25)).isoformat(),
                "capacity": 4,
            },
        )
        check("operator_create_slot", slot.status_code == 201)
        slot_id = slot.json()["event_slot"]["id"]
        check(
            "participant_sees_slot",
            any(
                s["id"] == slot_id
                for s in participant.get("/api/event-slots").json()["event_slots"]
            ),
        )
        application_id = None
        try:
            payload = {"request_key": str(uuid.uuid4()), "event_slot_ids": [slot_id]}
            created = change(participant, "POST", "/api/me/applications", payload)
            check("application_created", created.status_code == 201)
            application_id = created.json()["application"]["id"]
            replay = change(participant, "POST", "/api/me/applications", payload)
            check(
                "application_replay",
                replay.status_code == 200 and replay.json()["application"]["id"] == application_id,
            )
            path = f"/api/me/applications/{application_id}/payments"
            failed = change(
                participant,
                "POST",
                path,
                {
                    "request_key": str(uuid.uuid4()),
                    "product_code": "single",
                    "simulate_failure": True,
                },
            )
            check(
                "mock_failure",
                failed.status_code == 201 and failed.json()["payment"]["state"] == "FAILED",
            )
            payment_request = {"request_key": str(uuid.uuid4()), "product_code": "single"}
            paid = change(participant, "POST", path, payment_request)
            check(
                "mock_paid",
                paid.status_code == 201
                and paid.json()["payment"]["state"] == "PAID"
                and paid.json()["payment"]["mock"] is True
                and paid.json()["payment"]["amount_krw"] == 9900,
            )
            replay = change(participant, "POST", path, payment_request)
            check(
                "payment_replay",
                replay.status_code == 200
                and replay.json()["payment"]["id"] == paid.json()["payment"]["id"],
            )
            listed = participant.get("/api/me/applications").json()["applications"]
            application = next(a for a in listed if a["id"] == application_id)
            check("paid_matching_eligible", slot_id in application["matching_eligible_slot_ids"])
            admin = operator.get("/api/admin/applications")
            check(
                "operator_sees_application",
                admin.status_code == 200
                and any(a["id"] == application_id for a in admin.json()["applications"]),
            )
        finally:
            if application_id:
                canceled = change(
                    participant, "POST", f"/api/me/applications/{application_id}/cancel"
                )
                check(
                    "synthetic_application_canceled",
                    canceled.status_code == 200
                    and canceled.json()["application"]["state"] == "CANCELED",
                )
        entitlements = participant.get("/api/me/entitlements").json()["entitlements"]
        check(
            "single_grant_only",
            len([e for e in entitlements if e["application_id"] == application_id]) == 1,
        )
        for client in (participant, operator):
            check("logout", change(client, "POST", "/api/auth/logout").status_code == 200)
        print("PASS deployed_application_flow", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("FAIL deployed_application_flow " + type(error).__name__, flush=True)
        sys.exit(1)
