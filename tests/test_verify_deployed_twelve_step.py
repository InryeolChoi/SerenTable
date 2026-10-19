"""Pure helpers of scripts/verify_deployed_twelve_step.py (no server, no database)."""

import importlib.util
import json
from pathlib import Path
from urllib.error import URLError

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_deployed_twelve_step.py"
spec = importlib.util.spec_from_file_location("verify_deployed_twelve_step", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.mark.parametrize(
    ("origin", "local", "expected"),
    [
        ("https://chance.example/", False, "https://chance.example"),
        ("http://127.0.0.1:8001", True, "http://127.0.0.1:8001"),
        ("http://localhost:8001", True, "http://localhost:8001"),
    ],
)
def test_accepted_origins(origin, local, expected):
    assert verifier.validate_origin(origin, local) == expected


@pytest.mark.parametrize(
    ("origin", "local", "reason"),
    [
        ("http://chance.example", False, "https_required"),
        ("http://127.0.0.1:8001", False, "https_required"),
        ("http://chance.example", True, "local_http_only_for_loopback"),
        ("http://10.0.0.5:8001", True, "local_http_only_for_loopback"),
        ("https://user:pw@chance.example", False, "origin_has_credentials_or_query"),
        ("https://chance.example/api", False, "origin_not_bare"),
        ("", False, "origin_not_bare"),
        ("ftp://chance.example", True, "https_required"),
    ],
)
def test_refused_origins(origin, local, reason):
    with pytest.raises(ValueError, match=reason):
        verifier.validate_origin(origin, local)


def test_output_keeps_ids_and_redacts_anything_else():
    slot = "9e88cf24-9920-453c-a18c-035833d3a113"
    line = verifier.safe_line(
        "PASS", "worker_matching_run_succeeded", slot, "2026-10-19T10:41:07.297272+09:00", "1"
    )
    assert line == f"PASS worker_matching_run_succeeded {slot} 2026-10-19T10:41:07.297272+09:00 1"
    line = verifier.safe_line(
        "FAIL",
        "Bad Label!",
        '{"contact": "010-1234-5678"}',
        "synthetic-operator-password",
        "session=abc; HttpOnly",
        "status=409",
        "code=feedback_not_open",
    )
    assert line == (
        "FAIL unlabeled <redacted> <redacted> <redacted> status=409 code=feedback_not_open"
    )
    with pytest.raises(ValueError):
        verifier.safe_line("DEBUG", "x")


def test_request_keys_are_stable_per_slot_account_and_purpose():
    key = verifier.request_key("s1", "participant-01", "application")
    assert key == verifier.request_key("s1", "participant-01", "application")
    assert key != verifier.request_key("s2", "participant-01", "application")
    assert key != verifier.request_key("s1", "participant-02", "application")
    assert key != verifier.request_key("s1", "participant-01", "payment")


def test_private_leaks_find_keys_and_profile_values():
    assert verifier.private_leaks('{"display_name": "a"}', {"010-0000-0000"}) == []
    assert verifier.private_leaks('{"score": "70"}', set()) == ["score"]
    assert verifier.private_leaks('{"body": "010-0000-0000"}', {"010-0000-0000"}) == [
        "profile_value"
    ]


def test_venue_price_needs_a_band_every_member_accepts():
    low = {"meal_budget_bands": ["10000_20000", "20000_30000"]}
    mid = {"meal_budget_bands": ["20000_30000"]}
    assert verifier.venue_price([low, low]) == 15000
    assert verifier.venue_price([low, mid]) == 25000
    assert verifier.venue_price([low, {"meal_budget_bands": ["30000_plus"]}]) is None
    assert verifier.food_clear({"food_restrictions": {"status": "none"}, "allergies": {}}) is False


class FakeOpener:
    """Scripted transport: each entry is an exception to raise or (status, json body)."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def open(self, request, timeout):
        self.calls.append((request.get_method(), request.full_url.split("/api", 1)[1]))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        status, body = step
        return FakeResponse(status, body)


class FakeResponse:
    def __init__(self, status, body):
        self.code, self.headers, self.body = status, {}, json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_client(monkeypatch, *script):
    monkeypatch.setattr(verifier.time, "sleep", lambda _: None)
    client = verifier.Client("https://chance.example")
    client.opener = FakeOpener(*script)
    return client


TOKEN = (200, {"csrf_token": "t1"})


def test_reads_retry_a_transient_network_error(monkeypatch):
    client = fake_client(monkeypatch, URLError("reset"), (200, {"ok": True}))
    assert client.get("/api/health").status_code == 200
    assert len(client.opener.calls) == 2


def test_a_create_is_never_resent_after_a_network_error(monkeypatch):
    # The first POST may have committed server-side; resending could create a duplicate.
    client = fake_client(monkeypatch, TOKEN, TimeoutError(), (201, {}))
    with pytest.raises(TimeoutError):
        client.change("POST", "/api/admin/event-slots", {})
    assert client.opener.calls == [("GET", "/auth/csrf"), ("POST", "/admin/event-slots")]


def test_an_idempotent_write_may_be_resent(monkeypatch):
    client = fake_client(monkeypatch, TOKEN, URLError("reset"), (200, {}))
    assert client.change("PUT", "/api/me/profile", {}, retry=True).status_code == 200


def test_csrf_token_is_fetched_once_and_refreshed_only_when_rejected(monkeypatch):
    client = fake_client(
        monkeypatch,
        TOKEN,
        (200, {}),
        (200, {}),
        (403, {"detail": "csrf_rejected"}),
        (200, {"csrf_token": "t2"}),
        (200, {}),
    )
    assert client.change("PUT", "/api/me/profile", {}).status_code == 200
    assert client.change("PUT", "/api/me/consents", {}).status_code == 200
    assert client.change("PUT", "/api/me/profile", {}).status_code == 200
    assert [c for c in client.opener.calls if c[1] == "/auth/csrf"] == [("GET", "/auth/csrf")] * 2
    assert len(client.opener.calls) == 6


def test_a_rejection_that_is_not_csrf_is_returned_as_is(monkeypatch):
    client = fake_client(monkeypatch, TOKEN, (403, {"detail": "operator_required"}))
    assert client.change("POST", "/api/admin/event-slots", {}).status_code == 403
    assert len(client.opener.calls) == 2


def test_logout_is_cleanup_that_tries_every_account_and_never_prints_fail(monkeypatch, capsys):
    session = verifier.Session(verifier.Config("https://chance.example", "p", "o"))
    monkeypatch.setattr(verifier.time, "sleep", lambda _: None)
    session.operator.opener = FakeOpener((503, {}))  # csrf bootstrap fails
    scripts = [
        [TOKEN, (200, {})],
        [TOKEN, URLError("reset"), URLError("reset"), URLError("reset")],
        [TOKEN, (401, {"detail": "authentication_required"})],
        [TOKEN, (200, {})],
    ]
    for client, script in zip(session.members.values(), scripts, strict=True):
        client.opener = FakeOpener(*script)
    for client in (session.operator, *session.members.values()):
        client.logged_in = True
    session.logout()
    assert capsys.readouterr().out.splitlines() == [
        "INFO logout_incomplete operator",
        "INFO logout_incomplete participant_02",
        "INFO logout_incomplete participant_03",
    ]
    assert all(not c.opener.script for c in session.members.values())


def test_logout_skips_accounts_that_never_logged_in(capsys):
    session = verifier.Session(verifier.Config("https://chance.example", "p", "o"))
    for client in (session.operator, *session.members.values()):
        client.opener = FakeOpener()  # any request would fail the test
    session.logout()
    assert capsys.readouterr().out == ""


def test_a_slot_whose_create_response_was_lost_is_found_by_region_and_start():
    starts = verifier.parse_time("2026-10-19T01:20:07+00:00")
    slots = [
        {"id": "a", "region": {"code": "hongdae"}, "starts_at": "2026-10-19T10:20:08+09:00"},
        {"id": "b", "region": {"code": "gangnam"}, "starts_at": "2026-10-19T10:20:07+09:00"},
        {"id": "c", "region": {"code": "hongdae"}, "starts_at": "2026-10-19T10:20:07+09:00"},
    ]
    assert verifier.find_created_slot(slots, "hongdae", starts)["id"] == "c"
    assert verifier.find_created_slot(slots[:2], "hongdae", starts) is None


def test_tablemates_must_be_the_whole_table_by_display_name_only():
    four = [{"display_name": f"참가자{i}"} for i in range(4)]
    assert verifier.tablemates_display_name_only(four, 4) is True
    assert verifier.tablemates_display_name_only([], 4) is False  # never vacuously true
    assert verifier.tablemates_display_name_only(four[:3], 4) is False
    leaked = [*four[:3], {"display_name": "x", "contact": "010"}]
    assert verifier.tablemates_display_name_only(leaked, 4) is False


def test_notifications_count_only_for_this_table():
    notes = [
        {"kind": "CONFIRMED", "table_id": "t-old"},
        {"kind": "VENUE_ASSIGNED", "table_id": "t-old"},
        {"kind": "REMINDER", "table_id": "t-old"},
        {"kind": "CONFIRMED", "table_id": "t-new"},
        {"kind": "FEEDBACK_REMINDER", "table_id": "t-old"},
        {"kind": "TEST", "table_id": None},
        {"kind": "CONFIRMED"},  # an older server without table_id never counts
    ]
    assert verifier.table_notices(notes, "t-new") == [{"kind": "CONFIRMED", "table_id": "t-new"}]
    assert {n["kind"] for n in verifier.table_notices(notes, "t-old")} == {
        "CONFIRMED",
        "VENUE_ASSIGNED",
        "REMINDER",
        "FEEDBACK_REMINDER",
    }
    assert len(verifier.table_notices(notes, "t-old", "FEEDBACK_REMINDER")) == 1
    assert verifier.table_notices(notes, "t-new", "FEEDBACK_REMINDER") == []


@pytest.mark.parametrize(
    ("origin", "creating", "confirmed", "refused"),
    [
        ("https://chance.example", True, False, True),  # a real public slot needs opt-in
        ("https://chance.example", True, True, False),
        ("https://chance.example", False, False, False),  # resuming creates nothing
        ("http://127.0.0.1:8001", True, False, False),  # loopback is local testing
        ("http://localhost:8001", True, False, False),
    ],
)
def test_creating_a_public_slot_needs_explicit_confirmation(origin, creating, confirmed, refused):
    assert verifier.public_slot_needs_confirmation(origin, creating, confirmed) is refused


def test_run_refuses_a_public_slot_without_confirmation_before_any_request(monkeypatch, capsys):
    monkeypatch.setenv("DEPLOY_ORIGIN", "https://chance.example")
    monkeypatch.setenv("DEMO_PARTICIPANT_PASSWORD", "p")
    monkeypatch.setenv("DEMO_OPERATOR_PASSWORD", "o")
    monkeypatch.setattr(verifier, "Session", None)  # any network use would raise
    assert verifier.main(["run"]) == verifier.EXIT_REFUSED
    assert capsys.readouterr().out == "FAIL confirm_public_slot_required\n"


def test_only_state_changing_operator_actions_after_close_count():
    closes = verifier.parse_time("2026-10-19T10:00:00+09:00")
    rows = [
        {"action": "event_slot.create", "created_at": "2026-10-19T09:50:00+09:00"},
        {"action": "export", "created_at": "2026-10-19T10:30:00+09:00"},  # audited read
        {"action": "venue_food.approve", "created_at": "2026-10-19T10:05:00+09:00"},
        {"action": "exception_resolve", "created_at": "2026-10-19T10:00:00+09:00"},
        {"action": "some.future_change", "created_at": "2026-10-19T11:00:00+09:00"},
    ]
    assert [r["action"] for r in verifier.late_operator_actions(rows, closes)] == [
        "venue_food.approve",
        "exception_resolve",
        "some.future_change",
    ]
