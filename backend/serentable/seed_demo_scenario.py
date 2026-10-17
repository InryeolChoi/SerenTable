"""Prepare approved synthetic consent/application/mock-payment fixtures over HTTP.

An operator creates one dedicated capacity-100 slot with the ordinary admin UI/API and
passes its id explicitly. This command never creates/reschedules slots or triggers the
matcher. Stable request keys make a failed HTTP sequence resumable, not all-or-nothing.
"""

import argparse
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from http.client import HTTPException as HTTPProtocolError
from urllib.parse import urlsplit

from sqlalchemy.exc import SQLAlchemyError

from serentable.profile import POLICY_VERSION
from serentable.seed_synthetic_roster import COUNT, LOGIN_PREFIX, configuration


class ScenarioError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ScenarioError("scenario_redirect_refused")


class Client:
    def __init__(self, origin):
        self.origin = origin
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(self, path, method="GET", payload=None):
        headers = {"Origin": self.origin, "Accept": "application/json"}
        if method != "GET":
            headers["X-CSRF-Token"] = self.request("/api/auth/csrf")["csrf_token"]
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.origin + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=15) as response:
                body = response.read(8_000_001)
                if len(body) > 8_000_000:
                    raise ScenarioError("scenario_response_too_large")
                return json.loads(body)
        except (OSError, HTTPProtocolError, ValueError, KeyError):
            # Neither credentials, API bodies nor URLs belong in shared logs.
            raise ScenarioError("scenario_http_unavailable") from None

    def login(self, account, password):
        return self.request("/api/auth/login", "POST", {"login_id": account, "password": password})

    def logout(self):
        try:
            self.request("/api/auth/logout", "POST")
        except (ScenarioError, KeyError, TypeError):
            pass  # The ordinary revocable session will expire if the server is unavailable.


def origin_for(target):
    origin = os.environ["APP_ORIGIN"]
    parsed = urlsplit(origin)
    parsed.port  # Reject malformed ports before credentials are used.
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError
    if target == "railway":
        if origin != "https://chanceplate.up.railway.app":
            raise ValueError
    elif parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError
    return origin


def prepare(origin, slot_id, participant_password, operator_password):
    clients = []
    completed = 0
    try:
        operator = Client(origin)
        clients.append(operator)
        operator.login("operator", operator_password)
        slots = operator.request("/api/admin/event-slots")["event_slots"]
        slot = next((row for row in slots if row["id"] == slot_id), None)
        if slot is None or slot["capacity"] != COUNT:
            raise ScenarioError("scenario_dedicated_slot_required")
        expected = {
            f"{LOGIN_PREFIX}{index:03d}": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL, f"serentable:synthetic-demo:v1:{LOGIN_PREFIX}{index:03d}"
                )
            )
            for index in range(1, COUNT + 1)
        }
        roster = operator.request("/api/admin/participants")["participants"]
        known = {row["login_id"]: row for row in roster}
        if any(
            account not in known
            or known[account]["id"] != identifier
            or not known[account]["profile_complete"]
            for account, identifier in expected.items()
        ):
            raise ScenarioError("scenario_synthetic_roster_required")
        existing = operator.request("/api/admin/applications")["applications"]
        in_slot = [row for row in existing if any(c["id"] == slot_id for c in row["candidates"])]
        if any(row["participant"]["id"] not in expected.values() for row in in_slot):
            raise ScenarioError("scenario_mixed_slot_refused")
        if (
            not slot["recruiting"]
            and len(
                {
                    row["participant"]["id"]
                    for row in in_slot
                    if row["state"] == "SUBMITTED"
                    and any(p["state"] == "PAID" for p in row["payments"])
                }
            )
            != COUNT
        ):
            raise ScenarioError("scenario_closed_before_preparation")
        catalog = operator.request("/api/products")
        if catalog.get("mock") is not True:
            raise ScenarioError("scenario_mock_payment_required")
        policies = operator.request("/api/consent/policies")["policies"]
        if {p["purpose"] for p in policies} != {"privacy", "operation"} or any(
            p["version"] != POLICY_VERSION or "합성" not in p["title"] for p in policies
        ):
            raise ScenarioError("scenario_synthetic_policy_required")

        # Inspect every participant before any consent/application/payment writes. Existing
        # withdrawals are respected; this command never flips a prior refusal to accepted.
        participants = []
        for account, identifier in expected.items():
            client = Client(origin)
            clients.append(client)
            client.login(account, participant_password)
            consent = client.request("/api/me/consents")
            if consent["consents"] and not consent["complete"]:
                raise ScenarioError("scenario_existing_consent_change_refused")
            participants.append((client, identifier, consent["complete"]))
        for client, identifier, consent_complete in participants:
            if not consent_complete:
                client.request(
                    "/api/me/consents",
                    "PUT",
                    {
                        "consents": [
                            {"purpose": p["purpose"], "version": p["version"], "accepted": True}
                            for p in policies
                        ]
                    },
                )
            application = client.request(
                "/api/me/applications",
                "POST",
                {
                    "request_key": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"demo-app:{slot_id}:{identifier}")
                    ),
                    "event_slot_ids": [slot_id],
                },
            )["application"]
            if application["state"] != "SUBMITTED":
                raise ScenarioError("scenario_application_changed")
            payment = client.request(
                f"/api/me/applications/{application['id']}/payments",
                "POST",
                {
                    "request_key": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"demo-pay:{slot_id}:{identifier}")
                    ),
                    "product_code": "single",
                    "simulate_failure": False,
                },
            )["payment"]
            if payment["state"] != "PAID" or payment["mock"] is not True:
                raise ScenarioError("scenario_mock_payment_not_ready")
            completed += 1
    except ScenarioError as error:
        raise ScenarioError(f"{error}; completed={completed}") from None
    finally:
        for client in clients:
            client.logout()
    return {"synthetic": True, "slot_id": slot_id, "ready_participants": completed, "mock": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot-id", required=True, type=uuid.UUID)
    parser.add_argument("--target", choices=("local", "railway"), default="local")
    args = parser.parse_args()
    try:
        _, participant = configuration(args.target)
        origin = origin_for(args.target)
        operator = os.environ["DEMO_OPERATOR_PASSWORD"]
        if not 12 <= len(operator) <= 128:
            raise ValueError
    except (ValueError, KeyError, SQLAlchemyError):
        print("scenario_configuration_invalid", file=sys.stderr)
        return 2
    try:
        result = prepare(origin, str(args.slot_id), participant, operator)
    except (ScenarioError, KeyError, TypeError) as error:
        print(
            str(error) if isinstance(error, ScenarioError) else "scenario_response_invalid",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
