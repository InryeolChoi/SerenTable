import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from serentable.applications import router as applications_router
from serentable.auth import router as auth_router
from serentable.chat import router as chat_router
from serentable.database import database_engine
from serentable.events import router as events_router
from serentable.gatherings import router as gatherings_router
from serentable.match_resolution import router as resolution_router
from serentable.matching import router as matching_router
from serentable.notifications import router as notifications_router
from serentable.payments import router as payments_router
from serentable.profile import router as profile_router

app = FastAPI(title="SerenTable", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(events_router)
app.include_router(gatherings_router)
app.include_router(applications_router)
app.include_router(payments_router)
app.include_router(matching_router)
app.include_router(chat_router)
app.include_router(notifications_router)
app.include_router(resolution_router)


@app.exception_handler(RequestValidationError)
async def private_validation_error(request, error):
    # Preserve field locations while excluding submitted secrets and PII.
    details = [
        {key: item[key] for key in ("type", "loc", "msg") if key in item} for item in error.errors()
    ]
    return JSONResponse(
        status_code=422, content={"detail": details}, headers={"Cache-Control": "no-store"}
    )


@app.middleware("http")
async def private_api_errors(request, call_next):
    sensitive = request.url.path.startswith(
        ("/api/auth/", "/api/me/", "/api/admin/", "/api/event-slots", "/api/products")
    )
    try:
        response = await call_next(request)
    except SQLAlchemyError:
        if not sensitive:
            raise
        response = JSONResponse(status_code=503, content={"detail": "auth_storage_unavailable"})
    if sensitive:
        response.headers["Cache-Control"] = "no-store"
    return response


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


@app.get("/login", include_in_schema=False)
@app.get("/participant/profile", include_in_schema=False)
@app.get("/participant/consent", include_in_schema=False)
@app.get("/admin/participants", include_in_schema=False)
@app.get("/", include_in_schema=False)
@app.get("/participant", include_in_schema=False)
@app.get("/admin", include_in_schema=False)
@app.get("/admin/events", include_in_schema=False)
@app.get("/participant/events", include_in_schema=False)
@app.get("/participant/apply", include_in_schema=False)
@app.get("/participant/apply/review", include_in_schema=False)
@app.get("/admin/applications", include_in_schema=False)
def web_shell():
    if not (WEB_ROOT / "index.html").is_file():
        raise HTTPException(status_code=503, detail="web_build_unavailable")
    return FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/participant/payment/{application_id}", include_in_schema=False)
def payment_shell(application_id: uuid.UUID):
    # The id is only shape-checked here; ownership is enforced by the API the page calls.
    return web_shell()
