import base64
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.main import app
from serentable.webpush_transport import validate_subscription
from support import login, send, truncate


def subscription(endpoint="https://fcm.googleapis.com/fcm/send/synthetic"):
    def encoded(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    key = ec.generate_private_key(ec.SECP256R1()).public_key()
    return {
        "endpoint": endpoint,
        "keys": {
            "p256dh": encoded(key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)),
            "auth": encoded(b"synthetic-auth16"),
        },
    }


def test_provider_subscription_rejects_unsafe_urls_and_invalid_keys():
    valid = subscription()
    assert validate_subscription(valid)["endpoint"] == valid["endpoint"]
    apple = subscription("https://web.push.apple.com/QGuQyavXutnMH_synthetic")
    assert validate_subscription(apple)["endpoint"] == apple["endpoint"]
    for endpoint in [
        "http://fcm.googleapis.com/a",
        "https://127.0.0.1/a",
        "https://fcm.googleapis.com.evil.test/a",
        "https://user@fcm.googleapis.com/a",
        "https://fcm.googleapis.com:444/a",
        "https://fcm.googleapis.com/a#x",
        "https://fcm.googleapis.com/a\\b",
        "https://fcm.googleapis.com/a\n",
        "https://evil.push.apple.com/a",
        "https://web.push.apple.com.evil.test/a",
    ]:
        with pytest.raises(ValueError):
            validate_subscription(subscription(endpoint))
    for keys in [
        {"auth": "AA", "p256dh": valid["keys"]["p256dh"]},
        {"auth": valid["keys"]["auth"], "p256dh": "B" * 87},
    ]:
        with pytest.raises(ValueError):
            validate_subscription({"endpoint": valid["endpoint"], "keys": keys})


@pytest.fixture
def notifications_database(seeded_database):
    truncate("push_delivery, push_subscription, app_notification, gathering_exception")
    from serentable.notifications import router

    if not any(getattr(route, "path", "") == "/api/me/notifications" for route in app.routes):
        app.include_router(router)


def test_owner_notification_read_is_idempotent_and_private(notifications_database):
    from serentable.notifications import enqueue_notification

    with TestClient(app) as owner, TestClient(app) as other:
        assert owner.get("/api/me/notifications").status_code == 401
        user = login(owner)
        login(other, "participant-02")
        now = datetime.now(timezone.utc)
        with database_engine().begin() as connection:
            first = enqueue_notification(
                connection,
                user["id"],
                "test:one",
                "TEST",
                "새 안내",
                "앱 내 안내",
                "/participant",
                now,
            )
            assert (
                enqueue_notification(
                    connection,
                    user["id"],
                    "test:one",
                    "TEST",
                    "새 안내",
                    "앱 내 안내",
                    "/participant",
                    now,
                )
                == first
            )
        assert other.get("/api/me/notifications").json()["notifications"] == []
        assert send(other, "POST", f"/api/me/notifications/{first}/read").status_code == 404
        assert owner.post(f"/api/me/notifications/{first}/read").status_code == 403
        read = send(owner, "POST", f"/api/me/notifications/{first}/read")
        assert read.status_code == 200
        assert send(owner, "POST", f"/api/me/notifications/{first}/read").json() == read.json()
        items = owner.get("/api/me/notifications").json()["notifications"]
        assert len(items) == 1 and items[0]["read_at"] is not None
        assert items[0]["table_id"] is None  # not a table announcement
        assert items[0]["push_status"] == "not_subscribed"
        assert owner.get("/api/me/notifications").headers["cache-control"] == "no-store"


def test_subscription_owner_cannot_transfer_endpoint_and_keys_never_return(notifications_database):
    with TestClient(app) as owner, TestClient(app) as other, TestClient(app) as admin:
        login(owner)
        login(other, "participant-02")
        login(admin, "operator")
        payload = subscription()
        assert owner.post("/api/me/push-subscriptions", json=payload).status_code == 403
        first = send(owner, "POST", "/api/me/push-subscriptions", payload)
        assert first.status_code == 200
        assert set(first.json()) == {"id", "active"}
        assert send(owner, "POST", "/api/me/push-subscriptions", payload).json() == first.json()
        assert send(other, "POST", "/api/me/push-subscriptions", payload).status_code == 409
        sid = first.json()["id"]
        assert send(other, "DELETE", f"/api/me/push-subscriptions/{sid}").status_code == 404
        for _ in range(2):
            assert (
                send(owner, "DELETE", f"/api/me/push-subscriptions/{sid}").json()["active"] is False
            )
        assert send(admin, "POST", "/api/me/push-subscriptions", payload).status_code == 403
        invalid = send(owner, "POST", "/api/me/push-subscriptions", subscription("http://secret/a"))
        assert invalid.status_code == 422
        assert "secret" not in invalid.text and payload["keys"]["auth"] not in invalid.text
        assert owner.get("/api/admin/push-deliveries").status_code == 403
        assert set(owner.get("/api/me/push-config").json()) == {"public_key", "configured"}


class Provider:
    def __init__(self, status):
        self.status = status
        self.received = []

    def post(self, endpoint, *, data, headers, timeout):
        from requests import Response

        self.received.append((data, headers))
        response = Response()
        response.status_code = self.status
        response.reason = "synthetic"
        response._content = b"provider-secret-must-not-leak"
        return response


def configure(monkeypatch):
    monkeypatch.setenv(
        "WEB_PUSH_VAPID_PRIVATE_KEY", base64.urlsafe_b64encode(b"\x01" * 32).decode().rstrip("=")
    )
    monkeypatch.setenv("WEB_PUSH_VAPID_SUBJECT", "mailto:synthetic@example.test")


def prepare_notification(client):
    from serentable.notifications import enqueue_notification

    user = login(client)
    send(client, "POST", "/api/me/push-subscriptions", subscription())
    with database_engine().begin() as connection:
        return enqueue_notification(
            connection,
            user["id"],
            "delivery:one",
            "TEST",
            "비공개 이름",
            "비공개 연락처",
            "/participant",
            datetime.now(timezone.utc),
        )


def test_encrypted_provider_acceptance_and_duplicate_dispatch(notifications_database, monkeypatch):
    from serentable.notifications import dispatch_notifications

    configure(monkeypatch)
    provider = Provider(201)
    with TestClient(app) as owner, TestClient(app) as admin:
        prepare_notification(owner)
        login(admin, "operator")
        assert dispatch_notifications(session=provider) == 1
        assert dispatch_notifications(session=provider) == 0
        delivery = admin.get("/api/admin/push-deliveries").json()["deliveries"][0]
        assert delivery["state"] == "SENT" and delivery["attempts"] == 1
        assert delivery["sent_at"] is not None
        encrypted, headers = provider.received[0]
        assert b"\xeb\xb9\x84\xea\xb3\xb5\xea\xb0\x9c" not in encrypted
        assert "Authorization" in headers
        assert (
            owner.get("/api/me/notifications").json()["notifications"][0]["push_status"]
            == "accepted"
        )
        assert "provider-secret" not in admin.get("/api/admin/push-deliveries").text


def test_unconfigured_and_expired_are_unavailable_without_retry(
    notifications_database, monkeypatch
):
    from serentable.notifications import dispatch_notifications

    monkeypatch.delenv("WEB_PUSH_VAPID_PRIVATE_KEY", raising=False)
    with TestClient(app) as owner, TestClient(app) as admin:
        prepare_notification(owner)
        login(admin, "operator")
        provider = Provider(201)
        assert dispatch_notifications(session=provider) == 1
        assert provider.received == []
        row = admin.get("/api/admin/push-deliveries").json()["deliveries"][0]
        assert (row["state"], row["attempts"], row["last_error_code"]) == (
            "UNAVAILABLE",
            0,
            "server_unconfigured",
        )
        configure(monkeypatch)
        with database_engine().begin() as connection:
            # Time/state fixture models a newly queued delivery; runtime internals are not mocked.
            from sqlalchemy import text

            connection.execute(
                text("UPDATE push_delivery SET state='PENDING',next_attempt_at=CURRENT_TIMESTAMP")
            )
        assert dispatch_notifications(session=Provider(410)) == 1
        row = admin.get("/api/admin/push-deliveries").json()["deliveries"][0]
        assert row["state"] == "UNAVAILABLE" and row["last_error_code"] == "subscription_expired"
        assert row["sent_at"] is None


def test_three_attempts_one_and_five_minutes_then_single_operator_exception(
    notifications_database, monkeypatch
):
    from serentable.notifications import dispatch_notifications
    from sqlalchemy import text

    configure(monkeypatch)
    provider = Provider(503)
    with TestClient(app) as owner, TestClient(app) as admin:
        prepare_notification(owner)
        login(admin, "operator")
        for attempt, minutes in [(1, 1), (2, 5), (3, 5)]:
            before = datetime.now(timezone.utc)
            assert dispatch_notifications(session=provider) == 1
            row = admin.get("/api/admin/push-deliveries").json()["deliveries"][0]
            assert row["attempts"] == attempt
            assert row["state"] == ("FAILED" if attempt == 3 else "PENDING")
            assert row["sent_at"] is None
            assert (
                datetime.fromisoformat(row["next_attempt_at"]) - before
            ).total_seconds() >= minutes * 60 - 2
            assert dispatch_notifications(session=provider) == 0
            if attempt < 3:
                with database_engine().begin() as connection:
                    # Advance a scheduled job's due-time at the external clock fixture boundary.
                    connection.execute(
                        text("UPDATE push_delivery SET next_attempt_at=CURRENT_TIMESTAMP")
                    )
        assert len(provider.received) == 3
        errors = admin.get("/api/admin/gathering-exceptions").json()["exceptions"]
        assert len(errors) == 1 and errors[0]["reason_code"] == "push_attempts_exhausted"
        assert dispatch_notifications(session=provider) == 0
        assert len(admin.get("/api/admin/gathering-exceptions").json()["exceptions"]) == 1


def test_no_network_send_without_explicit_enable(notifications_database, monkeypatch):
    from serentable.notifications import dispatch_notifications

    configure(monkeypatch)
    monkeypatch.delenv("WEB_PUSH_NETWORK_ENABLED", raising=False)
    with TestClient(app) as owner, TestClient(app) as admin:
        prepare_notification(owner)
        login(admin, "operator")
        assert dispatch_notifications() == 1
        row = admin.get("/api/admin/push-deliveries").json()["deliveries"][0]
        assert (row["state"], row["attempts"], row["last_error_code"]) == (
            "UNAVAILABLE",
            0,
            "network_disabled",
        )
        assert (
            owner.get("/api/me/notifications").json()["notifications"][0]["body"] == "비공개 연락처"
        )


def test_transport_refuses_any_private_dns_answer_before_opening_socket(monkeypatch):
    import socket

    from serentable.webpush_transport import PinnedSession

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:127.0.0.1", 443, 0, 0)),
        ],
    )
    with pytest.raises(ValueError, match="push_dns_rejected"):
        PinnedSession().post(
            "https://fcm.googleapis.com/fcm/send/test", data=b"encrypted", headers={}, timeout=10
        )


def test_separate_dispatch_process_preserves_unavailable_notification(
    notifications_database, monkeypatch
):
    import os
    import subprocess
    import sys

    monkeypatch.delenv("WEB_PUSH_VAPID_PRIVATE_KEY", raising=False)
    with TestClient(app) as owner, TestClient(app) as admin:
        prepare_notification(owner)
        login(admin, "operator")
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from serentable.notifications import dispatch_notifications; "
                "print(dispatch_notifications())",
            ],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0 and result.stdout.strip() == "1"
        row = admin.get("/api/admin/push-deliveries").json()["deliveries"][0]
        assert row["state"] == "UNAVAILABLE" and row["sent_at"] is None
        assert len(owner.get("/api/me/notifications").json()["notifications"]) == 1
