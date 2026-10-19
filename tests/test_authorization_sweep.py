"""Work #10 A5-W2: authorization regression sweep over every mounted route.

The route list is read from the running FastAPI app, so a new route that is not classified
below fails these tests instead of silently skipping the role/CSRF checks. Role-to-route
rules follow security-verification-plan.md and ADR-0008 (participant data is
participant-only; operators receive 403 participant_required). Object checks compare a
participant's request for someone else's object with the same request for an id that does
not exist: both must be refused identically, so the response never confirms that the other
person's object exists.
"""

import json
import time
import uuid
from contextlib import ExitStack

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from serentable.chat import ensure_room
from serentable.database import database_engine
from serentable.main import app
from serentable.notifications import enqueue_notification
from sqlalchemy import text
from starlette.routing import Mount
from support import ORIGIN, login, send, truncate

# --- route classification -------------------------------------------------------------

# Public by design: liveness/readiness probes, the CSRF bootstrap, login itself (CSRF only),
# and static choice catalogs that contain no personal data.
PUBLIC_API = {
    ("GET", "/api/health"),
    ("GET", "/api/readiness"),
    ("GET", "/api/worker-health"),
    ("GET", "/api/auth/csrf"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/profile/options"),
    ("GET", "/api/consent/policies"),
}
# Any signed-in user, participant or operator.
ANY_USER_API = {
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/products"),
}
# Participant-only routes outside /api/me (ADR-0008 boundary; code: require_participant).
PARTICIPANT_API_OUTSIDE_ME = {("GET", "/api/event-slots")}
# Non-API GET routes only serve the static CSR shell or build assets; every data call the
# shell makes goes through /api and is covered below.
STATIC_PATHS = {"/favicon.svg", "/sw.js"}
STATIC_MOUNTS = {"/assets"}


def mounted_routes():
    """(method, path) for every API route of the app, including included routers."""

    def walk(routes, prefix=""):
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                yield from walk(inner.routes, prefix + route.include_context.prefix)
            else:
                yield prefix, route

    found = []
    for prefix, route in walk(app.routes):
        if isinstance(route, Mount):
            assert prefix + route.path in STATIC_MOUNTS, f"unclassified mount {route.path}"
            continue
        assert isinstance(route, APIRoute), f"unclassified route type {route!r}"
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            found.append((method, prefix + route.path))
    return found


def role_of(method, path):
    key = (method, path)
    if key in PUBLIC_API:
        return "public"
    if key in ANY_USER_API:
        return "user"
    if path.startswith("/api/admin/"):
        return "operator"
    if path.startswith("/api/me/") or key in PARTICIPANT_API_OUTSIDE_ME:
        return "participant"
    if not path.startswith("/api/") and method == "GET":
        if (
            path in STATIC_PATHS
            or path == "/"
            or path.startswith(("/login", "/participant", "/admin"))
        ):
            return "shell"
    raise AssertionError(f"unclassified route {method} {path}: add it to this sweep")


API_ROUTES = [(m, p) for m, p in mounted_routes() if role_of(m, p) != "shell"]
PROTECTED = [(m, p) for m, p in API_ROUTES if role_of(m, p) != "public"]
CHANGING = [(m, p) for m, p in API_ROUTES if m != "GET"]


def fill(path):
    """Concrete URL for a route template; random ids never name a real object."""
    while "{" in path:
        start, end = path.index("{"), path.index("}")
        path = path[:start] + str(uuid.uuid4()) + path[end + 1 :]
    return path


def test_the_sweep_sees_every_router_and_classifies_every_route():
    assert len(API_ROUTES) >= 60
    roles = {role_of(m, p) for m, p in API_ROUTES}
    assert roles == {"public", "user", "operator", "participant"}
    for method, path in PUBLIC_API | ANY_USER_API | PARTICIPANT_API_OUTSIDE_ME:
        assert (method, path) in API_ROUTES, f"stale allowlist entry {method} {path}"


@pytest.fixture
def clients(seeded_database):
    with TestClient(app) as anonymous, TestClient(app) as participant, TestClient(app) as operator:
        login(participant, "participant-01")
        login(operator, "operator")
        yield {"anonymous": anonymous, "participant": participant, "operator": operator}


def test_anonymous_requests_to_every_protected_route_are_401(clients):
    anonymous = clients["anonymous"]
    failures = []
    for method, path in PROTECTED:
        # A valid anonymous CSRF token: authentication, not CSRF, must be the refusal.
        response = send(anonymous, method, fill(path), {})
        if (response.status_code, response.json()) != (401, {"detail": "authentication_required"}):
            failures.append((method, path, response.status_code, response.text[:80]))
    assert failures == []


def test_participants_are_refused_every_operator_route(clients):
    participant = clients["participant"]
    failures = []
    for method, path in [r for r in PROTECTED if role_of(*r) == "operator"]:
        url = fill(path)
        response = participant.get(url) if method == "GET" else send(participant, method, url, {})
        if (response.status_code, response.json()) != (403, {"detail": "operator_required"}):
            failures.append((method, path, response.status_code, response.text[:80]))
    assert failures == []


def test_operators_are_refused_every_participant_only_route(clients):
    operator = clients["operator"]
    failures = []
    for method, path in [r for r in PROTECTED if role_of(*r) == "participant"]:
        url = fill(path)
        response = operator.get(url) if method == "GET" else send(operator, method, url, {})
        if (response.status_code, response.json()) != (403, {"detail": "participant_required"}):
            failures.append((method, path, response.status_code, response.text[:80]))
    assert failures == []


def test_every_state_changing_route_rejects_missing_or_foreign_origin_csrf(clients):
    failures = []
    for method, path in CHANGING:
        role = role_of(method, path)
        client = clients["operator" if role == "operator" else "participant"]
        if role == "public":
            client = clients["anonymous"]
        url = fill(path)
        token = client.get("/api/auth/csrf").json()["csrf_token"]
        attempts = {
            "no token": client.request(method, url, json={}, headers={"Origin": ORIGIN}),
            "foreign origin": client.request(
                method,
                url,
                json={},
                headers={"Origin": "https://evil.example", "X-CSRF-Token": token},
            ),
            "forged token": client.request(
                method, url, json={}, headers={"Origin": ORIGIN, "X-CSRF-Token": token + "x"}
            ),
        }
        for label, response in attempts.items():
            if (response.status_code, response.json()) != (403, {"detail": "csrf_rejected"}):
                failures.append((method, path, label, response.status_code, response.text[:80]))
    assert failures == []
    # Logout without CSRF was refused above, so both sessions are still live.
    assert clients["participant"].get("/api/auth/me").status_code == 200
    assert clients["operator"].get("/api/admin/session").status_code == 200


# --- object authorization ---------------------------------------------------------------

OUTSIDER = "participant-authz-outsider"
RATINGS = {
    "table_rating": 5,
    "conversation_rating": 4,
    "venue_rating": 3,
    "rejoin_intent": 5,
    "recommend_intent": 4,
}


def db_now(connection):
    return connection.execute(text("SELECT now()")).scalar_one()


@pytest.fixture
def two_owners(seeded_database):
    """participant-01's real confirmed (and ended) table with its chat room, notification
    and push subscription, plus an outsider with a submitted application of their own."""
    from serentable.matching import run_due_matches
    from test_feedback import end_slot
    from test_matching_runner import apply_and_pay, due_slot, prepare
    from test_notifications import subscription

    truncate("event_slot, participant_profile, consent_record, push_subscription, app_notification")
    # A synthetic participant who never joins the table (same demo password hash).
    with database_engine().begin() as connection:
        connection.execute(
            text(f"""INSERT INTO app_user(id,login_id,password_hash,role,active)
            SELECT gen_random_uuid(),'{OUTSIDER}',password_hash,role,true
            FROM app_user WHERE login_id='participant-01' ON CONFLICT(login_id) DO NOTHING""")
        )
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        outsider = stack.enter_context(TestClient(app))
        login(operator, "operator")
        for index, member in enumerate(members, 1):
            prepare(member, f"participant-0{index}")
        prepare(outsider, OUTSIDER)
        later = due_slot(operator, close_in=3600, days=10)
        slot = due_slot(operator, close_in=4)
        application = apply_and_pay(members[0], slot)
        for member in members[1:]:
            apply_and_pay(member, slot)
        own_application = apply_and_pay(outsider, later, paid=False)
        time.sleep(4.6)
        assert run_due_matches()[0]["seated_count"] == 4
        end_slot(slot)
        owner = members[0]
        ids = [m.get("/api/auth/me").json()["user"]["id"] for m in members]
        table_id = owner.get("/api/me/gatherings").json()["gatherings"][0]["id"]
        with database_engine().begin() as connection:
            room_id = str(ensure_room(connection, table_id, db_now(connection)))
            notification_id = str(
                enqueue_notification(
                    connection,
                    ids[0],
                    "authz:owner",
                    "TEST",
                    "안내",
                    "본인 안내",
                    "/participant",
                    db_now(connection),
                )
            )
        posted = send(
            owner,
            "POST",
            f"/api/me/rooms/{room_id}/messages",
            {"request_key": str(uuid.uuid4()), "body": "주인 메시지"},
        )
        assert posted.status_code == 201, posted.text
        subscribed = send(owner, "POST", "/api/me/push-subscriptions", subscription())
        assert subscribed.status_code == 200, subscribed.text
        (entitlement,) = owner.get("/api/me/entitlements").json()["entitlements"]
        yield {
            "owner": owner,
            "outsider": outsider,
            "member_ids": ids,
            "outsider_application": own_application,
            "owned": {
                "application_id": application,
                "entitlement_id": entitlement["id"],
                "notification_id": notification_id,
                "subscription_id": subscribed.json()["id"],
                "room_id": room_id,
                "table_id": table_id,
            },
        }


def body_for(method, path, context):
    """A valid body per state-changing object route, so ownership (not validation) decides."""
    if method in ("GET", "DELETE"):
        return None
    key = str(uuid.uuid4())
    bodies = {
        "cancel": None,
        "payments": {"request_key": key, "product_code": "single", "simulate_failure": False},
        "resolutions": {"request_key": key, "failure_run_id": str(uuid.uuid4()), "action": "HOLD"},
        "reuse": {"request_key": key, "application_id": context["outsider_application"]},
        "messages": {"request_key": key, "body": "끼어들기"},
        "read": None,
        "check-in": None,
        "feedback": RATINGS,
        "preferences": {
            "preferences": [{"target_id": context["member_ids"][1], "choice": "MEET_AGAIN"}]
        },
    }
    action = path.rsplit("/", 1)[1]
    assert action in bodies, f"no sweep body for {method} {path}: add one"
    return bodies[action]


# (status, detail) the owner receives for the fixture objects; detail None means a success
# body. The fixture table has ended and its application is confirmed and paid, so some
# writes return a documented domain refusal, which still proves the object was found.
OWNER_CONTROL = {
    ("GET", "/api/me/applications/{application_id}/alternatives"): (
        409,
        "alternatives_not_available",
    ),
    ("POST", "/api/me/applications/{application_id}/cancel"): (409, "application_cancel_closed"),
    ("POST", "/api/me/applications/{application_id}/payments"): (409, "payment_closed"),
    ("GET", "/api/me/rooms/{room_id}/messages"): (200, None),
    ("POST", "/api/me/rooms/{room_id}/messages"): (201, None),
    ("POST", "/api/me/notifications/{notification_id}/read"): (200, None),
    ("DELETE", "/api/me/push-subscriptions/{subscription_id}"): (200, None),
    ("POST", "/api/me/applications/{application_id}/resolutions"): (
        409,
        "resolution_not_available",
    ),
    ("POST", "/api/me/entitlements/{entitlement_id}/reuse"): (409, "entitlement_not_reusable"),
    ("POST", "/api/me/tables/{table_id}/check-in"): (409, "check_in_closed"),
    ("GET", "/api/me/tables/{table_id}/feedback"): (200, None),
    ("PUT", "/api/me/tables/{table_id}/feedback"): (200, None),
    ("PUT", "/api/me/tables/{table_id}/preferences"): (200, None),
    ("GET", "/api/me/tables/{table_id}/safety"): (200, None),
    ("POST", "/api/me/reports"): (201, None),
    ("POST", "/api/me/blocks"): (200, None),
}


def table_body(path, field, table_id, target_id):
    payload = {"dining_table_id": table_id, field: target_id}
    if path.endswith("reports"):
        payload["reason_code"] = "other"
    return payload


def owner_views(owner, owned):
    """What the owner can see; any successful foreign write would change one of these."""
    room, table = owned["room_id"], owned["table_id"]
    paths = [
        "/api/me/applications",
        "/api/me/entitlements",
        "/api/me/notifications",
        "/api/me/gatherings",
        "/api/me/rooms",
        f"/api/me/rooms/{room}/messages",
        f"/api/me/tables/{table}/feedback",
        f"/api/me/tables/{table}/safety",
        "/api/me/history",
    ]
    views = {}
    for path in paths:
        response = owner.get(path)
        views[path] = (response.status_code, response.json())
    return views


def test_another_participants_objects_are_refused_exactly_like_missing_ones(two_owners):
    owner, outsider, owned = two_owners["owner"], two_owners["outsider"], two_owners["owned"]
    before = owner_views(owner, owned)
    object_routes = [(m, p) for m, p in API_ROUTES if role_of(m, p) == "participant" and "{" in p]
    assert len(object_routes) >= 14
    body_routes = {("POST", "/api/me/reports"), ("POST", "/api/me/blocks")}
    assert {*object_routes, *body_routes} == set(OWNER_CONTROL), "classify the owner control"
    failures, controls = [], []
    for method, path in object_routes:
        foreign, missing = path, path
        for name in [part[1:-1] for part in path.split("/") if part.startswith("{")]:
            assert name in owned, f"no owned object for {{{name}}} in {path}: extend the fixture"
            foreign = foreign.replace(f"{{{name}}}", owned[name])
            missing = missing.replace(f"{{{name}}}", str(uuid.uuid4()))
        controls.append((method, path, foreign))
        results = []
        for url in (foreign, missing):
            payload = body_for(method, path, two_owners)
            response = (
                outsider.get(url) if method == "GET" else send(outsider, method, url, payload)
            )
            results.append((response.status_code, response.json()))
        if results[0] != results[1] or results[0][0] != 404:
            failures.append((method, path, results))
    # Reports and blocks name the table in the body rather than the path.
    reported = two_owners["member_ids"][1]
    for path, field in (("/api/me/reports", "reported_id"), ("/api/me/blocks", "blocked_id")):
        results = []
        for table in (owned["table_id"], str(uuid.uuid4())):
            response = send(outsider, "POST", path, table_body(path, field, table, reported))
            results.append((response.status_code, response.json()))
        if results[0] != results[1] or results[0][0] != 404:
            failures.append(("POST", path, results))
        controls.append(("POST", path, table_body(path, field, owned["table_id"], reported)))
    assert failures == []
    assert owner_views(owner, owned) == before
    # Positive control: the same fixture ids, requested by their owner, reach the handler and
    # return its own success or documented domain result, never the not-found refusal above.
    # Writes run only after the unchanged-views check, in route order.
    mismatched = []
    for method, path, target in controls:
        if isinstance(target, dict):  # a table named in the body
            response = send(owner, method, path, target)
        elif method == "GET":
            response = owner.get(target)
        else:
            response = send(owner, method, target, body_for(method, path, two_owners))
        actual = (response.status_code, response.json().get("detail"))
        if actual != OWNER_CONTROL[(method, path)]:
            mismatched.append((method, path, actual))
    assert mismatched == []


def test_a_participants_own_lists_never_contain_another_participants_objects(two_owners):
    outsider, owned = two_owners["outsider"], two_owners["owned"]
    foreign_ids = set(owned.values()) | set(two_owners["member_ids"])
    lists = [
        p for m, p in API_ROUTES if m == "GET" and role_of(m, p) == "participant" and "{" not in p
    ]
    assert len(lists) >= 10
    leaks = []
    for path in lists:
        response = outsider.get(path)
        assert response.status_code == 200, (path, response.text)
        body = json.dumps(response.json())
        leaks += [(path, value) for value in foreign_ids if value in body]
    assert leaks == []
