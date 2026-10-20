"""Successive independent HTTP scenarios must start without another scenario's data."""

import pytest
from fastapi.testclient import TestClient
from serentable.main import app
from support import login
from test_applications import create_slot, make_ready


@pytest.mark.parametrize("scenario", [1, 2])
def test_seeded_scenarios_cannot_inherit_profiles_or_event_slots(seeded_database, scenario):
    with TestClient(app) as operator, TestClient(app) as member:
        login(operator, "operator")
        login(member)
        assert operator.get("/api/admin/event-slots").json()["event_slots"] == []
        assert member.get("/api/me/profile").json()["profile"] is None
        make_ready(member)
        create_slot(operator, days=7 + scenario)
