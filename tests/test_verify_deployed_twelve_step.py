"""Pure helpers of scripts/verify_deployed_twelve_step.py (no server, no database)."""

import importlib.util
from pathlib import Path

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
