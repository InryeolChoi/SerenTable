"""Durable owner-only notifications and at-least-once Web Push dispatch."""

from datetime import timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from serentable.auth import (
    Principal,
    private_response,
    require_csrf_participant,
    require_operator,
    require_participant,
)
from serentable.database import database_engine
from serentable.webpush_transport import configuration, send_push, validate_subscription

router = APIRouter()


def enqueue_notification(connection, user_id, event_key, kind, title, body, url, now):
    if url not in (
        "/participant",
        "/participant/gatherings",
        "/participant/rooms",
        "/participant/history",
    ):
        raise ValueError("notification_url_not_allowed")
    notification_id = connection.execute(
        text("""INSERT INTO app_notification
        (id,user_id,event_key,kind,title,body,url,created_at)
        VALUES(:id,:user,:event,:kind,:title,:body,:url,:now)
        ON CONFLICT(user_id,event_key) DO UPDATE SET event_key=EXCLUDED.event_key RETURNING id"""),
        {
            "id": uuid4(),
            "user": user_id,
            "event": event_key,
            "kind": kind,
            "title": title,
            "body": body,
            "url": url,
            "now": now,
        },
    ).scalar_one()
    connection.execute(
        text("""INSERT INTO push_delivery
        (id,notification_id,subscription_id,state,attempts,next_attempt_at)
        SELECT gen_random_uuid(),:id,id,'PENDING',0,:now FROM push_subscription
        WHERE user_id=:user AND active ON CONFLICT(notification_id,subscription_id) DO NOTHING"""),
        {"id": notification_id, "user": user_id, "now": now},
    )
    return notification_id


@router.get("/api/me/notifications")
def notifications(user: Annotated[Principal, Depends(require_participant)]):
    with database_engine().connect() as connection:
        rows = (
            connection.execute(
                text("""SELECT n.id,n.kind,n.title,n.body,n.url,n.created_at,
            n.read_at, CASE WHEN EXISTS(SELECT 1 FROM push_delivery d WHERE d.notification_id=n.id
              AND d.state='SENT') THEN 'accepted' WHEN EXISTS(SELECT 1 FROM push_delivery d
              WHERE d.notification_id=n.id AND d.state='PENDING') THEN 'pending'
              WHEN EXISTS(SELECT 1 FROM push_delivery d WHERE d.notification_id=n.id
              AND d.state='FAILED') THEN 'failed' WHEN EXISTS(SELECT 1 FROM push_delivery d
              WHERE d.notification_id=n.id) THEN 'unavailable' ELSE 'not_subscribed' END push_status
            FROM app_notification n WHERE n.user_id=:user
            ORDER BY n.created_at DESC,n.id LIMIT 100"""),
                {"user": user.id},
            )
            .mappings()
            .all()
        )
    return private_response({"notifications": [serialize(row) for row in rows]})


def serialize(row):
    return {
        key: value.isoformat()
        if hasattr(value, "isoformat")
        else str(value)
        if isinstance(value, UUID)
        else value
        for key, value in row.items()
    }


@router.post("/api/me/notifications/{notification_id}/read")
def mark_read(notification_id: UUID, user: Annotated[Principal, Depends(require_csrf_participant)]):
    with database_engine().begin() as connection:
        row = (
            connection.execute(
                text("""UPDATE app_notification SET read_at=COALESCE(
            read_at,CURRENT_TIMESTAMP) WHERE id=:id AND user_id=:user RETURNING id,read_at"""),
                {"id": notification_id, "user": user.id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(404, "notification_not_found")
    return private_response(serialize(row))


@router.get("/api/me/push-config")
def push_config(user: Annotated[Principal, Depends(require_participant)]):
    config = configuration()
    return private_response(
        {"public_key": config[2] if config else None, "configured": config is not None}
    )


class SubscriptionKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(max_length=100)
    auth: str = Field(max_length=30)


class SubscriptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(max_length=4096)
    keys: SubscriptionKeys

    @model_validator(mode="after")
    def check_subscription(self):
        try:
            validate_subscription(self.model_dump())
        except (ValueError, KeyError, TypeError):
            raise ValueError("invalid_push_subscription") from None
        return self


@router.post("/api/me/push-subscriptions")
def subscribe(
    payload: SubscriptionInput, user: Annotated[Principal, Depends(require_csrf_participant)]
):
    with database_engine().begin() as connection:
        row = connection.execute(
            text("""INSERT INTO push_subscription
            (id,user_id,endpoint,p256dh,auth,created_at,active)
            VALUES(:id,:user,:endpoint,:p256dh,:auth,CURRENT_TIMESTAMP,true)
            ON CONFLICT(endpoint) DO UPDATE SET active=true,p256dh=EXCLUDED.p256dh,
            auth=EXCLUDED.auth WHERE push_subscription.user_id=EXCLUDED.user_id RETURNING id"""),
            {
                "id": uuid4(),
                "user": user.id,
                "endpoint": payload.endpoint,
                "p256dh": payload.keys.p256dh,
                "auth": payload.keys.auth,
            },
        ).first()
        if row is None:
            raise HTTPException(409, "subscription_unavailable")
    return private_response({"id": str(row.id), "active": True})


@router.delete("/api/me/push-subscriptions/{subscription_id}")
def unsubscribe(
    subscription_id: UUID, user: Annotated[Principal, Depends(require_csrf_participant)]
):
    with database_engine().begin() as connection:
        row = connection.execute(
            text("""UPDATE push_subscription SET active=false
            WHERE id=:id AND user_id=:user RETURNING id"""),
            {"id": subscription_id, "user": user.id},
        ).first()
        if row is None:
            raise HTTPException(404, "subscription_not_found")
    return private_response({"id": str(row.id), "active": False})


@router.get("/api/admin/push-deliveries")
def deliveries(user: Annotated[Principal, Depends(require_operator)]):
    with database_engine().connect() as connection:
        rows = (
            connection.execute(
                text("""SELECT id,notification_id,subscription_id,state,attempts,
            next_attempt_at,last_error_code,sent_at FROM push_delivery
            ORDER BY next_attempt_at DESC,id LIMIT 200""")
            )
            .mappings()
            .all()
        )
    return private_response({"deliveries": [serialize(row) for row in rows]})


@router.get("/api/admin/gathering-exceptions")
def exceptions(user: Annotated[Principal, Depends(require_operator)]):
    with database_engine().connect() as connection:
        rows = (
            connection.execute(
                text("""SELECT id,dining_table_id,kind,state,reason_code,
            created_at,updated_at FROM gathering_exception ORDER BY created_at DESC LIMIT 200""")
            )
            .mappings()
            .all()
        )
    return private_response({"exceptions": [serialize(row) for row in rows]})


def dispatch_notifications(*, session=None, limit=100):
    """One transaction/row lock across each send. Crash after acceptance can redeliver.

    session is solely the external HTTP provider boundary for isolated tests.
    The production path never accepts a caller-provided endpoint transport.
    """
    processed = 0
    for _ in range(limit):
        with database_engine().begin() as connection:
            row = (
                connection.execute(
                    text("""SELECT d.id,d.attempts,s.active,s.endpoint,s.p256dh,
                s.auth,s.id subscription_id,CURRENT_TIMESTAMP now FROM push_delivery d
                JOIN push_subscription s ON s.id=d.subscription_id
                WHERE d.state='PENDING' AND d.next_attempt_at<=CURRENT_TIMESTAMP
                ORDER BY d.next_attempt_at,d.id FOR UPDATE OF d SKIP LOCKED LIMIT 1""")
                )
                .mappings()
                .first()
            )
            if row is None:
                break
            result = (
                send_push(
                    {
                        "endpoint": row["endpoint"],
                        "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
                    },
                    session=session,
                )
                if row["active"]
                else "not_subscribed"
            )
            unavailable = result in (
                "not_subscribed",
                "server_unconfigured",
                "network_disabled",
                "subscription_expired",
            )
            attempts = row["attempts"] + (
                0 if unavailable and result != "subscription_expired" else 1
            )
            state = (
                "SENT"
                if result == "accepted"
                else "UNAVAILABLE"
                if unavailable
                else ("FAILED" if attempts >= 3 else "PENDING")
            )
            connection.execute(
                text("""UPDATE push_delivery SET state=:state,attempts=:attempts,
                next_attempt_at=:next,last_error_code=:error,sent_at=:sent WHERE id=:id"""),
                {
                    "state": state,
                    "attempts": attempts,
                    "id": row["id"],
                    "next": row["now"] + timedelta(minutes=1 if attempts <= 1 else 5),
                    "error": None if result == "accepted" else result,
                    "sent": row["now"] if result == "accepted" else None,
                },
            )
            if result == "subscription_expired":
                connection.execute(
                    text("UPDATE push_subscription SET active=false WHERE id=:id"),
                    {"id": row["subscription_id"]},
                )
            if state == "FAILED":
                connection.execute(
                    text("""INSERT INTO gathering_exception
                    (id,event_key,kind,state,reason_code,created_at,updated_at)
                    VALUES(:id,:event,'PUSH_DELIVERY','OPEN','push_attempts_exhausted',:now,:now)
                    ON CONFLICT(event_key) DO NOTHING"""),
                    {"id": uuid4(), "event": "push:" + str(row["id"]), "now": row["now"]},
                )
            processed += 1
    return processed
