"""Browser integrations require real root-scoped static assets, not the SPA shell."""

from fastapi.testclient import TestClient
from serentable.main import app


def test_brand_icon_and_push_worker_are_served_as_their_real_content():
    with TestClient(app) as client:
        icon = client.get("/favicon.svg")
        assert icon.status_code == 200
        assert icon.headers["content-type"].startswith("image/svg+xml")
        assert "<svg" in icon.text
        worker = client.get("/sw.js")
        assert worker.status_code == 200
        assert "javascript" in worker.headers["content-type"]
        assert "notificationclick" in worker.text and "addEventListener" in worker.text
        assert worker.headers["cache-control"] == "no-cache"
        assert client.get("/favicon-missing.svg").status_code == 404
