import pytest
from fastapi.testclient import TestClient
from serentable.main import app
from support import login, send, truncate


@pytest.fixture(autouse=True)
def profile_database(seeded_database):
    truncate("participant_profile, consent_record")


def put(client, path, payload):
    return send(client, "PUT", path, payload)


def test_participant_saves_and_reloads_incomplete_draft():
    with TestClient(app) as client:
        login(client)
        assert client.get("/api/me/profile").json()["profile"] is None
        saved = put(client, "/api/me/profile", {"display_name": "합성 참가자"})
        assert saved.status_code == 200
        assert saved.json()["complete"] is False
        assert "instagram_id" in saved.json()["missing_fields"]
        assert saved.json()["profile"]["allergies"] == {"status": "unknown", "details": None}
        assert client.get("/api/me/profile").json() == saved.json()
        assert saved.headers["cache-control"] == "no-store"


def complete_profile():
    return {
        "name": "합성 이름",
        "display_name": "테스트 식탁",
        "contact": "010-0000-0000",
        "instagram_id": "synthetic_demo",
        "birth_year": 1995,
        "gender": "기록한 성별",
        "occupation": "합성 직업",
        "mbtis": ["INTJ", "ENFP"],
        "interests": ["reading"],
        "self_traits": ["listener"],
        "desired_traits": ["different"],
        "meal_budget_bands": ["10000_20000"],
    }


def test_complete_profile_preserves_multi_choice_and_validates_canonical_inputs():
    with TestClient(app) as client:
        login(client)
        response = put(client, "/api/me/profile", complete_profile())
        assert response.json()["complete"] is True
        assert response.json()["profile"]["mbtis"] == ["INTJ", "ENFP"]
        for invalid in (
            {"mbtis": ["XXXX"]},
            {"interests": ["invented"]},
            {"birth_year": 9999},
            {"instagram_id": "bad/user"},
            {"allergies": {"status": "specified", "details": ""}},
            {"allergies": {"status": "none", "details": "peanut"}},
            {"user_id": "forged"},
            {"role": "operator"},
        ):
            result = put(client, "/api/me/profile", complete_profile() | invalid)
            assert result.status_code == 422
        assert client.get("/api/me/profile").json()["complete"] is True
        options = client.get("/api/profile/options").json()
        assert len(options["mbtis"]) == 16
        assert {"value": "reading", "label": "독서"} in options["interests"]


def test_consent_accept_replay_revoke_and_version_validation():
    with TestClient(app) as client:
        login(client)
        policies = client.get("/api/consent/policies")
        assert policies.status_code == 200
        assert {p["purpose"] for p in policies.json()["policies"]} == {"privacy", "operation"}
        assert client.get("/api/me/consents").json() == {"consents": [], "complete": False}
        decisions = {
            "consents": [
                {"purpose": p, "version": "demo-2026-10-16", "accepted": True}
                for p in ("privacy", "operation")
            ]
        }
        accepted = put(client, "/api/me/consents", decisions)
        assert accepted.status_code == 200
        assert accepted.json()["complete"] is True
        assert put(client, "/api/me/consents", decisions).json() == accepted.json()
        assert (
            put(
                client,
                "/api/me/consents",
                {
                    "consents": [
                        {"purpose": "privacy", "version": "demo-2026-10-16", "accepted": False}
                    ]
                },
            ).json()["complete"]
            is False
        )
        assert client.get("/api/me/consents").json()["complete"] is False
        assert (
            put(
                client,
                "/api/me/consents",
                {"consents": [{"purpose": "privacy", "version": "old", "accepted": True}]},
            ).status_code
            == 422
        )
        assert (
            put(client, "/api/me/consents", {"user_id": "forged", "consents": []}).status_code
            == 422
        )


def test_owner_isolation_and_operator_detail_never_expose_auth_secrets():
    with TestClient(app) as owner, TestClient(app) as other, TestClient(app) as operator:
        user = login(owner)
        login(other, "participant-02")
        put(owner, "/api/me/profile", complete_profile())
        assert other.get("/api/me/profile").json()["profile"] is None
        assert other.get("/api/admin/participants").status_code == 403
        assert other.get(f"/api/admin/participants/{user['id']}").status_code == 403
        assert other.get(f"/api/me/profile/{user['id']}").status_code == 404
        login(operator, "operator")
        listing = operator.get("/api/admin/participants")
        assert listing.status_code == 200
        assert all(
            set(item)
            == {"id", "login_id", "display_name", "profile_complete", "profile_unreadable"}
            for item in listing.json()["participants"]
        )
        detail = operator.get(f"/api/admin/participants/{user['id']}")
        assert detail.json()["profile"]["instagram_id"] == "synthetic_demo"
        assert set(detail.json()) == {
            "user",
            "profile",
            "profile_complete",
            "missing_fields",
            "profile_unreadable",
            "consents",
            "consents_complete",
        }
        assert "password" not in detail.text and "token" not in detail.text
        assert detail.headers["cache-control"] == "no-store"
        assert operator.get("/api/admin/participants/not-a-uuid").status_code == 422


def test_anonymous_and_missing_csrf_cannot_save_private_data():
    with TestClient(app) as client:
        assert client.get("/api/me/profile").status_code == 401
        assert client.get("/api/me/consents").status_code == 401
        assert client.put("/api/me/profile", json={}).status_code == 401
        login(client)
        assert client.put("/api/me/profile", json=complete_profile()).status_code == 403
        assert client.put("/api/me/consents", json={"consents": []}).status_code == 403
        assert client.get("/api/me/profile").json()["profile"] is None


def test_simultaneous_identical_consent_returns_same_recorded_state():
    from concurrent.futures import ThreadPoolExecutor

    with TestClient(app) as client:
        login(client)
        token = client.get("/api/auth/csrf").json()["csrf_token"]
        cookies = dict(client.cookies)
        payload = {
            "consents": [{"purpose": "privacy", "version": "demo-2026-10-16", "accepted": True}]
        }

        def submit(_):
            with TestClient(app) as parallel:
                parallel.cookies.update(cookies)
                return parallel.put(
                    "/api/me/consents",
                    json=payload,
                    headers={"Origin": "http://testserver", "X-CSRF-Token": token},
                )

        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(submit, range(4)))
        assert all(response.status_code == 200 for response in responses)
        assert all(response.json() == responses[0].json() for response in responses)
        assert client.get("/api/me/consents").json() == responses[0].json()


def test_csrf_is_rejected_before_body_validation():
    invalid = {"birth_year": "not-a-year", "unexpected": True}
    foreign = {"Origin": "https://attacker.example", "X-CSRF-Token": "forged"}
    with TestClient(app) as client:
        assert client.put("/api/me/profile", json=invalid).status_code == 401
        login(client)
        for path, body in (("/api/me/profile", invalid), ("/api/me/consents", {"x": 1})):
            assert client.put(path, json=body).status_code == 403
            response = client.put(path, json=body, headers=foreign)
            assert response.status_code == 403
            assert response.json() == {"detail": "csrf_rejected"}
        login_attempt = client.post("/api/auth/login", json={"login_id": "Bad!"}, headers=foreign)
        assert login_attempt.status_code == 403
        assert put(client, "/api/me/profile", invalid).status_code == 422


def test_unreadable_stored_profile_is_reported_per_row():
    from serentable.database import database_engine
    from sqlalchemy import text

    with TestClient(app) as owner, TestClient(app) as drifted, TestClient(app) as operator:
        login(owner)
        drifted_user = login(drifted, "participant-02")
        put(owner, "/api/me/profile", complete_profile())
        # No API can store an invalid profile; this simulates rows written by an older schema.
        with database_engine().begin() as connection:
            connection.execute(
                text("""INSERT INTO participant_profile(user_id,data)
                VALUES (:id, CAST(:data AS jsonb))"""),
                {"id": drifted_user["id"], "data": '{"birth_year": "not-a-year"}'},
            )
        login(operator, "operator")
        listing = operator.get("/api/admin/participants")
        assert listing.status_code == 200
        rows = {item["login_id"]: item for item in listing.json()["participants"]}
        assert rows["participant-01"]["profile_complete"] is True
        assert rows["participant-01"]["profile_unreadable"] is False
        assert rows["participant-02"]["profile_unreadable"] is True
        assert rows["participant-02"]["display_name"] == ""
        detail = operator.get(f"/api/admin/participants/{drifted_user['id']}")
        assert detail.status_code == 200
        assert detail.json()["profile"] is None
        assert detail.json()["profile_unreadable"] is True
        assert "not-a-year" not in detail.text
        own = drifted.get("/api/me/profile")
        assert own.status_code == 200
        assert own.json()["unreadable"] is True
        assert put(drifted, "/api/me/profile", complete_profile()).json()["unreadable"] is False


def test_operator_cannot_read_or_save_participant_profile_or_consent():
    with TestClient(app) as operator:
        login(operator, "operator")
        assert operator.get("/api/me/profile").status_code == 403
        assert operator.get("/api/me/consents").status_code == 403
        saved = put(operator, "/api/me/profile", complete_profile())
        assert saved.status_code == 403
        assert saved.json() == {"detail": "participant_required"}
        decision = {"purpose": "privacy", "version": "demo-2026-10-16", "accepted": True}
        consent = {"consents": [decision]}
        assert put(operator, "/api/me/consents", consent).status_code == 403
        assert operator.get("/api/admin/participants").status_code == 200
