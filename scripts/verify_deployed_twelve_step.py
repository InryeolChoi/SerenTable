"""Drive the PRD 12-step normal path over the public HTTPS URL, in resumable phases.

Run inside the deployed API container like verify_deployed_application.py (standard
library only). Reads DEPLOY_ORIGIN (or APP_ORIGIN), DEMO_PARTICIPANT_PASSWORD and
DEMO_OPERATOR_PASSWORD from the environment; DEPLOY_EXPECT_VERSION is checked when set.
There is no database access and no clock override: the real worker does every automatic
step, and later steps wait for real time (see docs/operations/deployed-twelve-step-
verification.md).

Phases (each re-runnable with the slot id that `prepare` prints):
  prepare                  operator slot + verified inventory, four participants apply/pay
  check-matching           worker match -> confirm -> venue -> room -> reminder, views
  check-event              in-event content, check-in, feedback after the end
  check-feedback-reminder  one reminder for the member who left no feedback (end + 24 h)
  run                      prepare, check-matching and check-event in sequence

Only fixed PASS/FAIL/WAIT/INFO labels, ids, timestamps and API error codes are printed;
never response bodies, cookies or passwords. Exit codes: 0 pass, 1 fail, 2 refused
configuration, 3 a later step is not reachable yet (re-run after the printed time).
The synthetic slot, applications, mock payments, check-ins, feedback and one room
message remain afterwards; nothing is refunded or deleted.
"""

import argparse
import ipaddress
import json
import os
import re
import secrets
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

PARTICIPANTS = tuple(f"participant-0{i}" for i in range(1, 5))
# participant-04 deliberately leaves no feedback so the 24-hour reminder can be checked.
SILENT = PARTICIPANTS[-1]
KEY_NAMESPACE = uuid.UUID("6f1d2c1e-6a52-4c8e-9a51-6d1b0c1f2a12")
VENUE_NAME = "배포 12단계 검증 식당"
BAND_PRICE = {"10000_20000": 15000, "20000_30000": 25000, "30000_plus": 35000}
RATINGS = dict.fromkeys(
    ("table_rating", "conversation_rating", "venue_rating", "rejoin_intent", "recommend_intent"), 4
)
# Response keys that must never reach another participant (ADR-0008, ADR-0011).
PRIVATE_KEYS = ("contact", "instagram_id", "birth_year", "score", "components", "policy")
# Fixed synthetic values used only with --normalize-profiles (same shape as the chain test).
NORMALIZED = {
    "birth_year": 1995,
    "gender": "합성",
    "occupation": "합성 검증",
    "mbtis": [],
    "interests": ["reading"],
    "self_traits": ["listener"],
    "desired_traits": ["different"],
    "meal_budget_bands": ["10000_20000"],
    "food_restrictions": {"status": "none"},
    "allergies": {"status": "none"},
}
DEFAULTS = {
    "name": "합성 검증",
    "display_name": "배포 확인 참가자",
    "contact": "010-0000-0000",
    "instagram_id": "synthetic_deploy_check",
    "birth_year": 1995,
    "gender": "합성",
    "occupation": "합성 검증",
    "interests": ["reading"],
    "self_traits": ["listener"],
    "desired_traits": ["different"],
    "meal_budget_bands": ["10000_20000"],
}

EXIT_FAIL, EXIT_REFUSED, EXIT_WAIT = 1, 2, 3
LABEL = re.compile(r"^[a-z0-9_]{1,64}$")
SAFE_VALUE = re.compile(
    r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # uuid
    r"|\d{4}-\d{2}-\d{2}T[0-9:.]+(?:[+-]\d{2}:\d{2}|Z)?"  # ISO timestamp
    r"|status=\d{3}|code=[a-z_]{1,48}|-?\d{1,6}(?:\.\d{1,2})?|[a-z0-9_]{1,32})$"
)


class Failed(Exception):
    """A check failed; the label was already printed."""


class NotYet(Exception):
    """A step needs real elapsed time; the label and time were already printed."""


# ---------------------------------------------------------------------- pure helpers


def validate_origin(origin, allow_local_http=False):
    """Return the normalized origin, or raise ValueError with a fixed reason."""
    origin = (origin or "").strip().rstrip("/")
    parts = urlsplit(origin)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("origin_has_credentials_or_query")
    if parts.path not in ("", "/") or not parts.hostname:
        raise ValueError("origin_not_bare")
    if parts.scheme == "https":
        return origin
    if parts.scheme == "http" and allow_local_http:
        host = parts.hostname
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if loopback:
            return origin
        raise ValueError("local_http_only_for_loopback")
    raise ValueError("https_required")


def safe_line(status, label, *values):
    """One output line built only from a fixed label and id-like values."""
    if status not in ("PASS", "FAIL", "WAIT", "INFO"):
        raise ValueError("unknown_status")
    if not LABEL.match(label):
        label = "unlabeled"
    shown = [str(v) if SAFE_VALUE.match(str(v)) else "<redacted>" for v in values if v != ""]
    return " ".join([status, label, *shown])


def request_key(slot_id, account, purpose):
    """Stable idempotency key per slot, account and purpose, so re-runs replay."""
    return str(uuid.uuid5(KEY_NAMESPACE, f"twelve-step:{slot_id}:{account}:{purpose}"))


def private_leaks(text, secrets_seen):
    """Names of private markers present in a participant-facing response text."""
    found = [key for key in PRIVATE_KEYS if f'"{key}"' in text]
    found += ["profile_value" for value in secrets_seen if value and value in text]
    return found


def venue_price(profiles):
    """A price every member's budget accepts, or None (venue allocation would fail)."""
    shared = set(BAND_PRICE)
    for profile in profiles:
        shared &= set(profile.get("meal_budget_bands") or [])
    for band in BAND_PRICE:
        if band in shared:
            return BAND_PRICE[band]
    return None


def food_clear(profile):
    return all(
        (profile.get(key) or {}).get("status") == "none"
        for key in ("food_restrictions", "allergies")
    )


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------- output


def say(status, label, *values):
    print(safe_line(status, label, *values), flush=True)


def check(label, condition, *values):
    if not condition:
        say("FAIL", label, *values)
        raise Failed(label)
    say("PASS", label, *values)


def detail_of(response):
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return "code=unknown"
    return f"code={detail}" if isinstance(detail, str) else "code=validation"


def expect(label, response, *statuses):
    if response.status_code not in statuses:
        say("FAIL", label, f"status={response.status_code}", detail_of(response))
        raise Failed(label)
    say("PASS", label)
    return response.json()


# ---------------------------------------------------------------------- HTTP


class Response:
    def __init__(self, status_code, headers, body):
        self.status_code, self.headers, self.body = status_code, headers, body

    def json(self):
        return json.loads(self.body)

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")


class Client:
    """Cookie-aware client; one per account. Never logs requests or responses."""

    def __init__(self, origin, timeout=25):
        self.origin, self.timeout = origin, timeout
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(self, method, path, payload=None, headers=None):
        body = None if payload is None else json.dumps(payload).encode()
        request = Request(
            self.origin + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        for attempt in range(3):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    return Response(response.code, response.headers, response.read())
            except HTTPError as response:
                with response:
                    return Response(response.code, response.headers, response.read())
            except (URLError, TimeoutError):
                # Transient network errors only; every write below is idempotent.
                if attempt == 2:
                    raise
                time.sleep(2)

    def get(self, path):
        return self.request("GET", path)

    def change(self, method, path, payload=None):
        token = self.get("/api/auth/csrf")
        if token.status_code != 200:
            say("FAIL", "csrf_bootstrap", f"status={token.status_code}")
            raise Failed("csrf_bootstrap")
        return self.request(
            method,
            path,
            payload=payload,
            headers={"Origin": self.origin, "X-CSRF-Token": token.json()["csrf_token"]},
        )

    def data(self, label, path):
        response = self.get(path)
        if response.status_code != 200:
            say("FAIL", label, f"status={response.status_code}", detail_of(response))
            raise Failed(label)
        return response.json()


class Session:
    """The operator and four participant clients of one phase."""

    def __init__(self, config):
        self.config = config
        self.operator = Client(config.origin)
        self.members = {account: Client(config.origin) for account in PARTICIPANTS}

    def login(self):
        expected = os.environ.get("DEPLOY_EXPECT_VERSION", "")
        health = self.operator.data("health", "/api/health")
        if expected:
            check("expected_deployed_version", health.get("version") == expected)
        accounts = [("operator", self.operator, self.config.operator_password)]
        accounts += [(a, c, self.config.participant_password) for a, c in self.members.items()]
        for account, client, password in accounts:
            response = client.change(
                "POST", "/api/auth/login", {"login_id": account, "password": password}
            )
            check(account.replace("-", "_") + "_login", response.status_code == 200)
        check(
            "private_no_store",
            self.operator.get("/api/auth/me").headers.get("cache-control") == "no-store",
        )

    def logout(self):
        for client in (self.operator, *self.members.values()):
            client.change("POST", "/api/auth/logout")

    def slot(self, slot_id):
        for slot in self.operator.data("admin_slots", "/api/admin/event-slots")["event_slots"]:
            if slot["id"] == slot_id:
                return slot
        say("FAIL", "slot_found", slot_id)
        raise Failed("slot_found")

    def application(self, account, slot_id):
        """Replay the stable application key: the same application, never a new one."""
        response = self.members[account].change(
            "POST",
            "/api/me/applications",
            {
                "request_key": request_key(slot_id, account, "application"),
                "event_slot_ids": [slot_id],
            },
        )
        if response.status_code not in (200, 201):
            say("FAIL", "application_lookup", f"status={response.status_code}", detail_of(response))
            raise Failed("application_lookup")
        application_id = response.json()["application"]["id"]
        listed = self.members[account].data("own_applications", "/api/me/applications")
        return next(a for a in listed["applications"] if a["id"] == application_id)


def wait_until(label, moment, deadline):
    """Sleep until a real moment, or report WAIT when it is past the phase deadline."""
    remaining = (moment - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        return
    if time.monotonic() + remaining > deadline:
        say("WAIT", label, moment.astimezone(timezone.utc).isoformat(timespec="seconds"))
        raise NotYet(label)
    time.sleep(remaining)


def phase_deadline(args, default_until):
    """Monotonic deadline: --timeout-seconds when given, else until a slot-derived moment."""
    if args.timeout_seconds is not None:
        return time.monotonic() + args.timeout_seconds
    seconds = (default_until - datetime.now(timezone.utc)).total_seconds()
    return time.monotonic() + max(60, seconds)


def poll(label, deadline, probe, interval=5):
    """Repeat a read-only probe until it returns a value or the phase deadline passes."""
    while True:
        value = probe()
        if value:
            return value
        if time.monotonic() + interval > deadline:
            say("FAIL", label, "code=timeout")
            raise Failed(label)
        time.sleep(interval)


# ---------------------------------------------------------------------- phases


def prepare(session, args):
    operator, members = session.operator, session.members
    check(
        "participant_admin_denied",
        members[PARTICIPANTS[0]].get("/api/admin/applications").status_code == 403,
    )
    policies = members[PARTICIPANTS[0]].data("consent_policies", "/api/consent/policies")
    profiles = []
    for account, client in members.items():
        name = account.replace("-", "_")
        state = client.data(name + "_profile_read", "/api/me/profile")
        profile = dict(state["profile"] or {})
        changed = False
        for key, value in DEFAULTS.items():
            if not profile.get(key):
                profile[key], changed = value, True
        # A food condition never entered ("unknown") is filled like any missing field;
        # an entered ("specified") one is only replaced with --normalize-profiles.
        for key in ("food_restrictions", "allergies"):
            if (profile.get(key) or {}).get("status", "unknown") == "unknown":
                profile[key], changed = {"status": "none"}, True
        if args.normalize_profiles:
            for key, value in NORMALIZED.items():
                if profile.get(key) != value:
                    profile[key], changed = value, True
        if changed or not state["complete"]:
            saved = client.change("PUT", "/api/me/profile", profile)
            check(name + "_profile_complete", saved.status_code == 200 and saved.json()["complete"])
            profile = saved.json()["profile"]
        else:
            say("PASS", name + "_profile_complete")
        profiles.append(profile)
        if not client.data(name + "_consent_read", "/api/me/consents")["complete"]:
            decisions = [
                {"purpose": p["purpose"], "version": p["version"], "accepted": True}
                for p in policies["policies"]
                if p["required"]
            ]
            accepted = client.change("PUT", "/api/me/consents", {"consents": decisions})
            check(
                name + "_consent_complete",
                accepted.status_code == 200 and accepted.json()["complete"],
            )
        else:
            say("PASS", name + "_consent_complete")
    price = venue_price(profiles)
    check("shared_meal_budget", price is not None)
    check("food_conditions_none", all(food_clear(p) for p in profiles))

    if args.slot_id:
        slot = session.slot(args.slot_id)
        say("PASS", "slot_resumed", slot["id"])
    else:
        regions = operator.data("regions", "/api/admin/regions")["regions"]
        check("region_known", any(r["code"] == args.region for r in regions))
        now = datetime.now(timezone.utc)
        closes = now + timedelta(minutes=args.close_minutes)
        # (region, start) is unique; a random second avoids colliding with other slots.
        starts = closes + timedelta(
            minutes=args.start_after_close_minutes, seconds=secrets.randbelow(50) + 1
        )
        created = operator.change(
            "POST",
            "/api/admin/event-slots",
            {
                "region_code": args.region,
                "starts_at": starts.isoformat(),
                "ends_at": (starts + timedelta(minutes=args.duration_minutes)).isoformat(),
                "closes_at": closes.isoformat(),
                "matches_at": closes.isoformat(),
                "capacity": 4,
            },
        )
        slot = expect("operator_create_slot", created, 201)["event_slot"]
    slot_id = slot["id"]
    say("INFO", "slot_id", slot_id)
    for moment in ("closes_at", "matches_at", "starts_at", "ends_at"):
        say("INFO", moment, slot[moment])

    inventory = operator.data("venue_inventory_read", "/api/admin/venue-inventory")["inventory"]
    if any(item["event_slot_id"] == slot_id for item in inventory):
        say("PASS", "verified_inventory_present")
    else:
        expect(
            "verified_inventory_registered",
            operator.change(
                "POST",
                "/api/admin/venue-inventory",
                {
                    "event_slot_id": slot_id,
                    "name": VENUE_NAME,
                    "address": "합성 주소 (배포 검증)",
                    "map_url": "https://map.naver.com/",
                    "price_krw": price,
                    "capacity": 6,
                },
            ),
            201,
        )

    for account, client in members.items():
        name = account.replace("-", "_")
        if parse_time(slot["closes_at"]) <= datetime.now(timezone.utc):
            # Resumed after the close: only replay what already exists.
            application = session.application(account, slot_id)
            check(name + "_paid_by_close", slot_id in application["matching_eligible_slot_ids"])
            continue
        visible = client.data(name + "_open_slots", "/api/event-slots")["event_slots"]
        check(name + "_sees_slot", any(s["id"] == slot_id for s in visible))
        payload = {
            "request_key": request_key(slot_id, account, "application"),
            "event_slot_ids": [slot_id],
        }
        created = client.change("POST", "/api/me/applications", payload)
        application_id = expect(name + "_application", created, 200, 201)["application"]["id"]
        replay = client.change("POST", "/api/me/applications", payload)
        check(
            name + "_application_replay",
            replay.status_code == 200 and replay.json()["application"]["id"] == application_id,
        )
        application = session.application(account, slot_id)
        if application["payment_required"]:
            path = f"/api/me/applications/{application_id}/payments"
            payment = {
                "request_key": request_key(slot_id, account, "payment"),
                "product_code": "single",
            }
            paid = expect(name + "_mock_paid", client.change("POST", path, payment), 200, 201)
            check(
                name + "_mock_payment_state",
                paid["payment"]["state"] == "PAID" and paid["payment"]["mock"] is True,
            )
            replay = client.change("POST", path, payment)
            check(
                name + "_payment_replay",
                replay.status_code == 200
                and replay.json()["payment"]["id"] == paid["payment"]["id"],
            )
            application = session.application(account, slot_id)
        else:
            source = (application.get("coverage") or {}).get("source")
            say(
                "INFO",
                name + ("_covered_by_membership" if source == "membership" else "_already_paid"),
            )
        check(name + "_matching_eligible", slot_id in application["matching_eligible_slot_ids"])
        say("INFO", name + "_application_id", application_id)
    admin = operator.data("admin_applications", "/api/admin/applications")["applications"]
    check(
        "operator_sees_four_applications",
        sum(1 for a in admin if slot_id in [c["id"] for c in a["candidates"]]) >= 4,
    )
    return slot_id


def own_views(session, account, table_id, room_id):
    """Participant-facing texts that must stay free of private data."""
    client = session.members[account]
    paths = ["/api/me/applications", "/api/me/gatherings", "/api/me/rooms", "/api/me/history"]
    if room_id:
        paths.append(f"/api/me/rooms/{room_id}/messages")
    if table_id:
        paths.append(f"/api/me/tables/{table_id}/feedback")
    return [client.data("view_read", path) for path in paths]


def check_privacy(session, table_id, room_id):
    # Every member's own contact/Instagram/name must not appear in anyone's shared views.
    secrets_seen = set()
    display_names = set()
    profiles = {}
    for account, client in session.members.items():
        profile = client.data("profile_read", "/api/me/profile")["profile"] or {}
        profiles[account] = profile
        display_names.add(profile.get("display_name") or "")
    for profile in profiles.values():
        for key in ("contact", "instagram_id", "name"):
            value = str(profile.get(key) or "")
            if len(value) >= 3 and value not in display_names:
                secrets_seen.add(value)
    for account in PARTICIPANTS:
        texts = json.dumps(own_views(session, account, table_id, room_id), ensure_ascii=False)
        leaks = private_leaks(texts, secrets_seen)
        check(account.replace("-", "_") + "_no_private_fields", not leaks, *sorted(set(leaks)))


def find_run(operator, slot_id):
    runs = operator.data("match_runs", "/api/admin/match-runs")["match_runs"]
    mine = [r for r in runs if r["event_slot"]["id"] == slot_id]
    return max(mine, key=lambda r: r["attempt"]) if mine else None


def our_table(session, slot_id):
    """Table and room of participant-01's confirmed seat in this slot."""
    application = session.application(PARTICIPANTS[0], slot_id)
    matching = application["matching"] or {}
    table = matching.get("table") or {}
    gatherings = session.members[PARTICIPANTS[0]].data("gatherings", "/api/me/gatherings")
    gathering = next((g for g in gatherings["gatherings"] if g["id"] == table.get("id")), None)
    return table.get("id"), gathering


def room_messages(session, account, room_id):
    path = f"/api/me/rooms/{room_id}/messages"
    return session.members[account].data("room_messages", path)["messages"]


def system_bodies(messages):
    return [m["body"] for m in messages if m["kind"] == "SYSTEM"]


def check_matching(session, args):
    operator, slot_id = session.operator, args.slot_id
    slot = session.slot(slot_id)
    deadline = phase_deadline(args, parse_time(slot["matches_at"]) + timedelta(minutes=10))
    wait_until("matching_time", parse_time(slot["matches_at"]), deadline)

    def finished():
        run = find_run(operator, slot_id)
        return run if run and run["state"] == "SUCCEEDED" else None

    run = poll("worker_matching_run_succeeded", deadline, finished)
    say("PASS", "worker_matching_run_succeeded", run["id"], f"{run['attempt']}")
    seated = {m["login_id"]: m for m in run["members"]}
    for account in PARTICIPANTS:
        member = seated.get(account) or {}
        check(
            account.replace("-", "_") + "_seated",
            member.get("outcome") == "SEATED",
            f"code={(member.get('reason_code') or member.get('outcome') or 'absent').lower()}",
        )
    table_ids = {seated[a]["dining_table_id"] for a in PARTICIPANTS}
    check("one_table_for_four", len(table_ids) == 1 and None not in table_ids)
    (table_id,) = table_ids
    table = next(t for t in run["tables"] if t["id"] == table_id)
    check("table_size_4_to_6", 4 <= table["member_count"] <= 6, f"{table['member_count']}")
    min_score = float(run["policy"]["min_score"])
    check("table_meets_min_score", float(table["score"]) >= min_score)
    say("INFO", "table_new_component", table["components"].get("new", "0"))

    for account in PARTICIPANTS:
        name = account.replace("-", "_")
        application = session.application(account, slot_id)
        matching = application["matching"] or {}
        check(name + "_confirmed", matching.get("state") == "CONFIRMED")
        mine = matching.get("table") or {}
        check(name + "_same_table", mine.get("id") == table_id)
        check(
            name + "_tablemates_display_name_only",
            all(set(m) == {"display_name"} for m in mine.get("members", [])),
        )
        coverage = (application.get("coverage") or {}).get("entitlement") or {}
        check(
            name + "_right_used_once",
            coverage.get("state") == "USED" or coverage.get("kind") == "MEMBERSHIP",
        )

    def gathered():
        _, gathering = our_table(session, slot_id)
        if not gathering or gathering["venue_state"] != "ASSIGNED" or not gathering["room_id"]:
            return None
        bodies = system_bodies(room_messages(session, PARTICIPANTS[0], gathering["room_id"]))
        markers = ("모임이 확정되었습니다", "예약명", "하루 안에 시작")
        return gathering if all(any(m in b for b in bodies) for m in markers) else None

    gathering = poll("venue_room_and_reminder_posted", deadline, gathered)
    say("PASS", "venue_room_and_reminder_posted")
    check("venue_is_verified_inventory", gathering["venue"]["name"] == VENUE_NAME)
    check("reservation_name_present", bool(gathering["venue"]["reservation_name"]))
    room_id = gathering["room_id"]
    for account in PARTICIPANTS:
        name = account.replace("-", "_")
        rooms = session.members[account].data("rooms", "/api/me/rooms")["rooms"]
        check(name + "_room_member", any(r["id"] == room_id for r in rooms))
        kinds = {
            n["kind"]
            for n in session.members[account].data("notifications", "/api/me/notifications")[
                "notifications"
            ]
        }
        check(name + "_notified", {"CONFIRMED", "VENUE_ASSIGNED", "REMINDER"} <= kinds)

    # One user message in the room, replayed with the same key, read by a tablemate.
    path = f"/api/me/rooms/{room_id}/messages"
    message = {
        "request_key": request_key(slot_id, PARTICIPANTS[0], "room-message"),
        "body": "안녕하세요, 배포 검증 메시지입니다.",
    }
    sent = expect(
        "room_message_sent",
        session.members[PARTICIPANTS[0]].change("POST", path, message),
        200,
        201,
    )
    replay = session.members[PARTICIPANTS[0]].change("POST", path, message)
    check(
        "room_message_replay",
        replay.status_code == 200 and replay.json()["message"]["id"] == sent["message"]["id"],
    )
    seen = room_messages(session, PARTICIPANTS[1], room_id)
    check(
        "tablemate_sees_message_with_display_name_only",
        any(
            m["id"] == sent["message"]["id"] and set(m["author"] or {}) == {"display_name"}
            for m in seen
        ),
    )
    check_privacy(session, table_id, room_id)
    check(
        "outsider_room_denied",
        session.operator.get(path).status_code in (403, 404),
    )
    check_operator_untouched(session, slot_id, table_id)
    if args.previous_slot_id:
        previous = find_run(operator, args.previous_slot_id)
        check("previous_run_found", previous is not None and previous["state"] == "SUCCEEDED")
        earlier = next(
            (
                t
                for t in previous["tables"]
                if t["id"]
                in {
                    m["dining_table_id"]
                    for m in previous["members"]
                    if m["login_id"] in PARTICIPANTS
                }
            ),
            None,
        )
        check(
            "next_matching_counts_previous_meeting",
            earlier is not None
            and float(table["components"]["new"]) < 100
            and float(table["components"]["new"]) <= float(earlier["components"]["new"]),
        )
    say("INFO", "table_id", table_id)
    say("INFO", "room_id", room_id)


def check_operator_untouched(session, slot_id, table_id, expect_checkins=None):
    """Step 12: no operator action after the close, and no open exception for this slot."""
    operator = session.operator
    slot = session.slot(slot_id)
    closes = parse_time(slot["closes_at"])
    targets = [slot_id, table_id]
    inventory = operator.data("venue_inventory_read", "/api/admin/venue-inventory")["inventory"]
    targets += [i["id"] for i in inventory if i["event_slot_id"] == slot_id]
    late = []
    for target in targets:
        rows = operator.data("audit", f"/api/admin/audit?target_id={target}&limit=200")["audit"]
        late += [r for r in rows if parse_time(r["created_at"]) >= closes]
    check("no_operator_action_after_close", not late)
    exceptions = operator.data("exceptions", "/api/admin/exceptions?state=OPEN")["exceptions"]
    check(
        "no_open_exception_for_slot",
        not [
            e
            for e in exceptions
            if e.get("event_slot_id") == slot_id or e.get("dining_table_id") == table_id
        ],
    )
    view = operator.data("dashboard", f"/api/admin/dashboard?event_slot_id={slot_id}")["slots"][0]
    check("dashboard_open_exceptions_zero", view["open_exception_count"] == 0)
    check("dashboard_confirmed_at_least_four", view["matching"]["confirmed_count"] >= 4)
    check(
        "dashboard_venue_and_room_per_table",
        view["gathering"]["venue_assigned"]
        == view["matching"]["table_count"]
        == view["gathering"]["room_count"],
    )
    if expect_checkins is not None:
        attendance = view["attendance"]
        check("dashboard_check_ins", attendance["check_in_count"] >= expect_checkins)
        check("dashboard_no_show_candidates_zero", attendance["no_show_candidate_count"] == 0)
        check("dashboard_feedback_submitted", attendance["feedback_submitted"] >= 3)


def check_event(session, args):
    slot_id = args.slot_id
    slot = session.slot(slot_id)
    starts, ends = parse_time(slot["starts_at"]), parse_time(slot["ends_at"])
    deadline = phase_deadline(args, ends + timedelta(minutes=3))
    table_id, gathering = our_table(session, slot_id)
    check("confirmed_table_found", bool(table_id and gathering and gathering["room_id"]))
    room_id = gathering["room_id"]
    first = session.members[PARTICIPANTS[0]]
    feedback_path = f"/api/me/tables/{table_id}/feedback"
    if datetime.now(timezone.utc) < ends:
        early = first.change("PUT", feedback_path, RATINGS)
        check(
            "feedback_closed_before_end",
            early.status_code == 409 and detail_of(early) == "code=feedback_not_open",
        )

    wait_until("event_start", starts, deadline)

    def started():
        bodies = system_bodies(room_messages(session, PARTICIPANTS[0], room_id))
        return [b for b in bodies if "오늘의 대화 주제" in b]

    topics = poll("in_event_content_posted", deadline, started)
    check("in_event_content_once", len(topics) == 1)
    for account in PARTICIPANTS:
        name = account.replace("-", "_")
        path = f"/api/me/tables/{table_id}/check-in"
        if datetime.now(timezone.utc) > ends:
            # Resumed after the end: an earlier run must already have checked in.
            replay = session.members[account].change("POST", path)
            check(name + "_checked_in", replay.status_code == 200)
            continue
        checked = expect(
            name + "_check_in", session.members[account].change("POST", path), 200, 201
        )
        replay = session.members[account].change("POST", path)
        check(
            name + "_check_in_replay",
            replay.status_code == 200
            and replay.json()["check_in"]["checked_in_at"] == checked["check_in"]["checked_in_at"],
        )
    before_end = len(room_messages(session, PARTICIPANTS[0], room_id))

    wait_until("event_end", ends, deadline)
    for account in PARTICIPANTS:
        name = account.replace("-", "_")
        if account == SILENT:
            say("INFO", name + "_feedback_left_empty_for_reminder")
            continue
        saved = session.members[account].change("PUT", feedback_path, RATINGS)
        check(name + "_feedback_after_end", saved.status_code == 200)
    revised = first.change("PUT", feedback_path, {**RATINGS, "venue_rating": 5})
    check("feedback_revised", revised.status_code == 200)
    state = first.data("feedback_read", feedback_path)
    check(
        "feedback_saved_privately",
        state["open"] and (state["feedback"] or {}).get("venue_rating") == 5,
    )
    # Two worker cycles after the end: nothing is posted retroactively.
    time.sleep(min(25, max(0, deadline - time.monotonic())))
    after = room_messages(session, PARTICIPANTS[0], room_id)
    check(
        "no_post_after_end",
        len(after) == before_end
        or all(parse_time(m["created_at"]) < ends for m in after if m["kind"] == "SYSTEM"),
    )
    check_privacy(session, table_id, room_id)
    check_operator_untouched(session, slot_id, table_id, expect_checkins=4)
    reminder_at = ends + timedelta(hours=24)
    say("INFO", "feedback_reminder_due_after", reminder_at.isoformat(timespec="seconds"))


def check_feedback_reminder(session, args):
    slot = session.slot(args.slot_id)
    due = parse_time(slot["ends_at"]) + timedelta(hours=24)
    now = datetime.now(timezone.utc)
    if now < due:
        say("WAIT", "feedback_reminder_due", due.isoformat(timespec="seconds"))
        raise NotYet("feedback_reminder_due")
    check("within_reminder_window_7_days", now < parse_time(slot["ends_at"]) + timedelta(days=7))
    deadline = phase_deadline(args, now + timedelta(minutes=2))

    def reminded():
        notes = session.members[SILENT].data("notifications", "/api/me/notifications")
        return [
            n
            for n in notes["notifications"]
            if n["kind"] == "FEEDBACK_REMINDER" and parse_time(n["created_at"]) >= due
        ]

    found = poll("silent_member_reminded", deadline, reminded)
    check("silent_member_reminded_once", len(found) == 1)


# ---------------------------------------------------------------------- CLI


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--allow-local-http",
        action="store_true",
        help="permit http:// only for a loopback origin (local testing)",
    )
    common.add_argument(
        "--timeout-seconds",
        type=float,
        help="phase wait budget; default: matching +10 min, event end +3 min, reminder 2 min",
    )
    slot = argparse.ArgumentParser(add_help=False)
    slot.add_argument("--slot-id", type=uuid.UUID)
    timing = argparse.ArgumentParser(add_help=False)
    timing.add_argument("--region", default="hongdae")
    timing.add_argument("--close-minutes", type=float, default=3)
    timing.add_argument("--start-after-close-minutes", type=float, default=8)
    timing.add_argument("--duration-minutes", type=float, default=10)
    timing.add_argument("--normalize-profiles", action="store_true")
    timing.add_argument("--previous-slot-id", type=uuid.UUID)
    root = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = root.add_subparsers(dest="phase", required=True)
    sub.add_parser("prepare", parents=[common, slot, timing])
    matching = sub.add_parser("check-matching", parents=[common, slot])
    matching.add_argument("--previous-slot-id", type=uuid.UUID)
    sub.add_parser("check-event", parents=[common, slot])
    sub.add_parser("check-feedback-reminder", parents=[common, slot])
    sub.add_parser("run", parents=[common, slot, timing])
    return root


class Config:
    def __init__(self, origin, participant_password, operator_password):
        self.origin = origin
        self.participant_password = participant_password
        self.operator_password = operator_password


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        origin = validate_origin(
            os.environ.get("DEPLOY_ORIGIN", os.environ.get("APP_ORIGIN", "")),
            args.allow_local_http,
        )
    except ValueError as error:
        say("FAIL", "origin_refused", f"code={error}")
        return EXIT_REFUSED
    passwords = [
        os.environ.get(n, "") for n in ("DEMO_PARTICIPANT_PASSWORD", "DEMO_OPERATOR_PASSWORD")
    ]
    if not all(passwords):
        say("FAIL", "demo_password_environment_required")
        return EXIT_REFUSED
    if (
        args.phase in ("check-matching", "check-event", "check-feedback-reminder")
        and not args.slot_id
    ):
        say("FAIL", "slot_id_required")
        return EXIT_REFUSED
    if (
        args.phase in ("prepare", "run")
        and min(args.close_minutes, args.start_after_close_minutes, args.duration_minutes) <= 0
    ):
        say("FAIL", "timing_must_be_positive")
        return EXIT_REFUSED
    if args.phase in ("prepare", "run") and args.start_after_close_minutes >= 24 * 60:
        # The worker posts the day-before reminder at confirmation only when the start is
        # within 24 hours; check-matching expects it, so keep the start inside that window.
        say("FAIL", "start_must_be_within_24h_of_close")
        return EXIT_REFUSED
    if args.slot_id:
        args.slot_id = str(args.slot_id)
    if getattr(args, "previous_slot_id", None):
        args.previous_slot_id = str(args.previous_slot_id)
    session = Session(Config(origin, *passwords))
    phase = args.phase.replace("-", "_")
    try:
        session.login()
        if args.phase in ("prepare", "run"):
            args.slot_id = prepare(session, args)
        if args.phase == "check-matching" or args.phase == "run":
            check_matching(session, args)
        if args.phase == "check-event" or args.phase == "run":
            check_event(session, args)
        if args.phase == "check-feedback-reminder":
            check_feedback_reminder(session, args)
    except NotYet:
        say("WAIT", phase, args.slot_id or "")
        return EXIT_WAIT
    except Failed:
        say("FAIL", phase)
        return EXIT_FAIL
    except Exception as error:  # never print the message: it may contain response data
        say("FAIL", phase, type(error).__name__.lower()[:32])
        return EXIT_FAIL
    finally:
        try:
            session.logout()
        except Exception:
            pass
    say("PASS", phase, args.slot_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
