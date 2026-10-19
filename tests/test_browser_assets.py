"""Browser integrations require real root-scoped static assets, not the SPA shell."""

from fastapi.testclient import TestClient
from serentable.main import app


def test_brand_icon_and_push_worker_are_served_as_their_real_content():
    with TestClient(app) as client:
        icon = client.get("/favicon.svg")
        assert icon.status_code == 200
        assert icon.headers["content-type"].startswith("image/svg+xml")
        assert "<svg" in icon.text
        home_icon = client.get("/apple-touch-icon.png")
        assert home_icon.status_code == 200
        assert home_icon.headers["content-type"] == "image/png"
        assert home_icon.content.startswith(b"\x89PNG")
        worker = client.get("/sw.js")
        assert worker.status_code == 200
        assert "javascript" in worker.headers["content-type"]
        assert "notificationclick" in worker.text and "addEventListener" in worker.text
        assert worker.headers["cache-control"] == "no-cache"
        assert client.get("/favicon-missing.svg").status_code == 404
