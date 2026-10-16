"""Same-origin, server-revocable authentication for the synthetic demo."""

import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from itsdangerous import URLSafeTimedSerializer

router = APIRouter()


@dataclass(frozen=True)
class Principal:
    id: str
    login_id: str
    role: str


@dataclass(frozen=True)
class Settings:
    origin: str
    key: str
    secure: bool
    session_name: str
    nonce_name: str
    ttl: int


def served_over_https(request: Request) -> bool:
    """Railway terminates TLS at its edge, which always sets X-Forwarded-Proto: https.

    Railway publishes no stable proxy CIDR, so uvicorn's proxy allowlist cannot name it.
    Only this scheme header is read; client-address headers remain untrusted.
    """
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def settings(request: Request) -> Settings:
    origin = os.getenv("APP_ORIGIN", "")
    key = os.getenv("AUTH_SIGNING_KEY", "")
    try:
        parsed = urlsplit(origin)
        parsed.port
    except ValueError:
        raise HTTPException(503, "auth_configuration_unavailable") from None
    production = (
        os.getenv("APP_ENV") == "production"
        or os.getenv("RAILWAY_ENVIRONMENT_NAME", "").lower() == "production"
    )
    valid_origin = (
        parsed.scheme in ("http", "https")
        and bool(parsed.netloc)
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
        and not parsed.username
        and not parsed.password
    )
    if not valid_origin or len(key) < 32:
        raise HTTPException(503, "auth_configuration_unavailable")
    if production and (parsed.scheme != "https" or not served_over_https(request)):
        raise HTTPException(503, "auth_configuration_unavailable")
    try:
        ttl = int(os.getenv("AUTH_SESSION_TTL_SECONDS", "43200"))
        if not 1 <= ttl <= 604800:
            raise ValueError
    except ValueError:
        raise HTTPException(503, "auth_configuration_unavailable") from None
    secure = parsed.scheme == "https"
    prefix = "__Host-" if secure else "dev-"
    return Settings(
        origin, key, secure, prefix + "serentable_session", prefix + "serentable_csrf", ttl
    )


def private_response(content: dict) -> JSONResponse:
    return JSONResponse(content, headers={"Cache-Control": "no-store"})


def set_cookie(response: JSONResponse, name: str, value: str, config: Settings):
    response.set_cookie(name, value, secure=config.secure, httponly=True, samesite="lax", path="/")


def csrf_serializer(config: Settings):
    return URLSafeTimedSerializer(config.key, salt="serentable-csrf-v1")


@router.get("/api/auth/csrf")
def csrf(request: Request):
    config = settings(request)
    nonce = request.cookies.get(config.nonce_name) or secrets.token_urlsafe(32)
    token = csrf_serializer(config).dumps(
        {"nonce": nonce, "session": session_binding(request, config)}
    )
    response = private_response({"csrf_token": token})
    set_cookie(response, config.nonce_name, nonce, config)
    return response


# The value carried by the browser is never persisted in PostgreSQL.
def digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def session_binding(request: Request, config: Settings) -> str:
    value = request.cookies.get(config.session_name)
    return digest(value) if value else "anonymous"


def require_csrf(request: Request):
    from itsdangerous import BadSignature

    config = settings(request)
    if request.headers.get("origin") != config.origin:
        raise HTTPException(403, "csrf_rejected")
    token = request.headers.get("x-csrf-token", "")
    nonce = request.cookies.get(config.nonce_name, "")
    if not token or not nonce or len(token) > 2048 or len(nonce) > 128:
        raise HTTPException(403, "csrf_rejected")
    try:
        payload = csrf_serializer(config).loads(token, max_age=3600)
        valid = (
            isinstance(payload, dict)
            and isinstance(payload.get("nonce"), str)
            and secrets.compare_digest(payload["nonce"], nonce)
            and isinstance(payload.get("session"), str)
            and secrets.compare_digest(payload["session"], session_binding(request, config))
        )
    except (BadSignature, TypeError, ValueError):
        valid = False
    if not valid:
        raise HTTPException(403, "csrf_rejected")


def require_user(request: Request) -> Principal:
    from sqlalchemy import text

    from serentable.database import database_engine

    config = settings(request)
    token = request.cookies.get(config.session_name, "")
    if not token or len(token) > 128:
        raise HTTPException(401, "authentication_required")
    with database_engine().connect() as connection:
        row = (
            connection.execute(
                text("""
                SELECT u.id, u.login_id, u.role FROM app_user u
                JOIN auth_session s ON s.user_id = u.id
                WHERE s.token_hash = :token AND s.revoked_at IS NULL
                AND s.expires_at > CURRENT_TIMESTAMP AND u.active
            """),
                {"token": digest(token)},
            )
            .mappings()
            .first()
        )
    if row is None:
        raise HTTPException(401, "authentication_required")
    return Principal(str(row["id"]), row["login_id"], row["role"])


def require_participant(request: Request) -> Principal:
    """Participant-only data such as the private profile; operators are refused."""
    user = require_user(request)
    if user.role != "participant":
        raise HTTPException(403, "participant_required")
    return user


def require_csrf_participant(request: Request) -> Principal:
    """Authorize, then check CSRF, before FastAPI validates the request body."""
    user = require_participant(request)
    require_csrf(request)
    return user


def require_operator(request: Request) -> Principal:
    user = require_user(request)
    if user.role != "operator":
        raise HTTPException(403, "operator_required")
    return user


def user_json(user: Principal) -> dict:
    return {"id": user.id, "login_id": user.login_id, "role": user.role}


from pwdlib import PasswordHash  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

password_hasher = PasswordHash.recommended()
# Verify unknown accounts too, without storing any usable credential.
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    password: str = Field(min_length=1, max_length=128)


@router.post("/api/auth/login", dependencies=[Depends(require_csrf)])
def login(payload: LoginInput, request: Request):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    from serentable.database import database_engine

    config = settings(request)
    now = datetime.now(timezone.utc)
    # A process-wide limit is defined below; each account is also serialized in PG.
    # Busy hashing is a server capacity condition, distinct from the per-account 429.
    if not hash_slots.acquire(blocking=False):
        raise HTTPException(503, "login_busy", headers={"Retry-After": "1"})
    try:
        with database_engine().begin() as connection:
            key = digest(payload.login_id)
            connection.execute(
                text("""
                INSERT INTO auth_login_limit(login_key, failures, window_started)
                VALUES (:key, 0, :now) ON CONFLICT DO NOTHING
            """),
                {"key": key, "now": now},
            )
            limit = (
                connection.execute(
                    text("""
                SELECT failures, window_started FROM auth_login_limit
                WHERE login_key = :key FOR UPDATE
            """),
                    {"key": key},
                )
                .mappings()
                .one()
            )
            fresh_window = limit["window_started"] <= now - timedelta(minutes=5)
            failures = 0 if fresh_window else limit["failures"]
            if failures >= 5:
                raise HTTPException(429, "login_temporarily_limited")
            row = (
                connection.execute(
                    text("""
                SELECT id, login_id, role, password_hash, active FROM app_user
                WHERE login_id = :login_id
            """),
                    {"login_id": payload.login_id},
                )
                .mappings()
                .first()
            )
            valid = password_hasher.verify(
                payload.password, row["password_hash"] if row else dummy_hash
            )
            if not valid or not row or not row["active"]:
                connection.execute(
                    text("""
                    UPDATE auth_login_limit SET failures = :failures,
                    window_started = :started WHERE login_key = :key
                """),
                    {
                        "failures": failures + 1,
                        "started": now if fresh_window else limit["window_started"],
                        "key": key,
                    },
                )
                result = None
            else:
                connection.execute(
                    text("""
                    UPDATE auth_login_limit SET failures = 0, window_started = :now
                    WHERE login_key = :key
                """),
                    {"key": key, "now": now},
                )
                old_token = request.cookies.get(config.session_name)
                if old_token:
                    connection.execute(
                        text("""
                        UPDATE auth_session SET revoked_at = :now
                        WHERE token_hash = :token AND revoked_at IS NULL
                    """),
                        {"now": now, "token": digest(old_token)},
                    )
                token = secrets.token_urlsafe(32)
                connection.execute(
                    text("""
                    INSERT INTO auth_session(token_hash, user_id, created_at, expires_at)
                    VALUES (:token, :user_id, :now, :expires)
                """),
                    {
                        "token": digest(token),
                        "user_id": row["id"],
                        "now": now,
                        "expires": now + timedelta(seconds=config.ttl),
                    },
                )
                result = Principal(str(row["id"]), row["login_id"], row["role"])
    finally:
        hash_slots.release()
    if result is None:
        raise HTTPException(401, "invalid_credentials")
    response = private_response({"user": user_json(result)})
    set_cookie(response, config.session_name, token, config)
    set_cookie(response, config.nonce_name, secrets.token_urlsafe(32), config)
    return response


from threading import BoundedSemaphore  # noqa: E402

hash_slots = BoundedSemaphore(2)


@router.get("/api/auth/me")
def me(request: Request):
    return private_response({"user": user_json(require_user(request))})


@router.get("/api/admin/session")
def admin_session(request: Request):
    return private_response({"user": user_json(require_operator(request))})


@router.post("/api/auth/logout")
def logout(request: Request):
    from sqlalchemy import text

    from serentable.database import database_engine

    require_user(request)
    require_csrf(request)
    config = settings(request)
    with database_engine().begin() as connection:
        connection.execute(
            text("""
            UPDATE auth_session SET revoked_at = CURRENT_TIMESTAMP
            WHERE token_hash = :token AND revoked_at IS NULL
        """),
            {"token": digest(request.cookies[config.session_name])},
        )
    response = private_response({"status": "logged_out"})
    for name in (config.session_name, config.nonce_name):
        response.delete_cookie(name, path="/", secure=config.secure, httponly=True, samesite="lax")
    return response
