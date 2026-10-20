"""Read-only alternatives for the participant's own unseated application."""

import time
import uuid
from contextlib import ExitStack

from fastapi.testclient import TestClient
from serentable.main import app
from serentable.matching import run_slot_matching
from support import login
from test_applications import apply, create_slot
from test_matching_runner import (  # noqa: F401
    apply_and_pay,
    due_slot,
    matching_database,
    prepare,
)


def test_unseated_participant_sees_open_alternatives_without_moving_or_spending():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        participant = stack.enter_context(TestClient(app))
        login(operator, "operator")
        prepare(participant, "participant-01")
        failed_slot = due_slot(operator)
        application_id = apply_and_pay(participant, failed_slot)
        alternative = create_slot(operator, days=10, region="gangnam")
        already_chosen = create_slot(operator, days=11, region="jamsil")
        assert apply(participant, [already_chosen]).status_code == 201
        time.sleep(3.6)
        assert run_slot_matching(failed_slot)["seated_count"] == 0
        before = participant.get("/api/me/applications").json()
        passes = participant.get("/api/me/entitlements").json()
        path = f"/api/me/applications/{application_id}/alternatives"
        response = participant.get(path)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["pending_candidates"] == []
        assert [slot["id"] for slot in body["alternatives"]] == [alternative]
        assert all(slot["recruiting"] for slot in body["alternatives"])
        assert set(body["alternatives"][0]) == {
            "id",
            "region",
            "starts_at",
            "ends_at",
            "closes_at",
            "matches_at",
            "capacity",
            "recruiting",
            # PRD §7.4 group of this slot relative to the participant's own choices.
            "preference",
        }
        assert participant.get(path).json() == body
        assert participant.get("/api/me/applications").json() == before
        assert participant.get("/api/me/entitlements").json() == passes
        assert passes["entitlements"][0]["state"] == "HELD"


def test_alternatives_keep_unprocessed_consented_candidates_as_waiting():
    with TestClient(app) as operator, TestClient(app) as participant:
        login(operator, "operator")
        prepare(participant, "participant-01")
        failed_slot = due_slot(operator)
        pending_slot = create_slot(operator, days=8, region="gangnam")
        application_id = apply(participant, [failed_slot, pending_slot]).json()["application"]["id"]
        from test_payments import pay

        assert pay(participant, application_id, "single").status_code == 201
        create_slot(operator, days=10, region="jamsil")
        time.sleep(3.6)
        assert run_slot_matching(failed_slot)["seated_count"] == 0
        response = participant.get(f"/api/me/applications/{application_id}/alternatives")
        assert response.status_code == 200, response.text
        body = response.json()
        assert [slot["id"] for slot in body["pending_candidates"]] == [pending_slot]
        assert body["alternatives"] == []


def test_alternative_lookup_enforces_owner_role_and_unseated_state():
    with TestClient(app) as operator, TestClient(app) as owner, TestClient(app) as other:
        login(operator, "operator")
        prepare(owner, "participant-01")
        login(other, "participant-02")
        application_id = apply_and_pay(owner, create_slot(operator))
        path = f"/api/me/applications/{application_id}/alternatives"
        assert owner.get(path).status_code == 409
        for inaccessible in (path, f"/api/me/applications/{uuid.uuid4()}/alternatives"):
            response = other.get(inaccessible)
            assert response.status_code == 404
            assert response.json() == {"detail": "application_not_found"}
        assert operator.get(path).status_code == 403
        with TestClient(app) as anonymous:
            assert anonymous.get(path).status_code == 401
