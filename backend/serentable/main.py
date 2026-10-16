import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from serentable.auth import router as auth_router
from serentable.database import database_engine
from serentable.profile import router as profile_router

app = FastAPI(title="SerenTable", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth_router)
app.include_router(profile_router)


@app.get("/api/health")
def health():
    return {
        "status": "alive",
        "version": os.getenv("APP_VERSION", os.getenv("RAILWAY_GIT_COMMIT_SHA", "development")),
    }


@app.get("/api/readiness")
def readiness():
    try:
        with database_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503, content={"status": "unavailable", "database": "unavailable"}
        )
    return {"status": "ready", "database": "connected"}


@app.get("/api/worker-health")
def worker_health():
    try:
        with database_engine().connect() as connection:
            alive = connection.execute(
                text("""
                SELECT last_seen > CURRENT_TIMESTAMP - INTERVAL '30 seconds'
                FROM worker_heartbeat WHERE name = 'scheduler'
            """)
            ).scalar()
        if alive:
            return {"status": "alive"}
    except Exception:
        pass
    return JSONResponse(status_code=503, content={"status": "unavailable"})


# Only these placeholder routes are public. No administrative data is exposed.
WEB_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (WEB_ROOT / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_ROOT / "assets"), name="assets")


@app.get("/", include_in_schema=False)
@app.get("/participant", include_in_schema=False)
@app.get("/admin", include_in_schema=False)
def web_shell():
    if not (WEB_ROOT / "index.html").is_file():
        raise HTTPException(status_code=503, detail="web_build_unavailable")
    return FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-cache"})
