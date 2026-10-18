"""Durable confirmed-table chat, with a shared room lock for every publisher."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from serentable.auth import (
    Principal,
    private_response,
    require_csrf_participant,
    require_participant,
)
from serentable.database import database_engine

router = APIRouter()

MEMBERSHIP = """FROM chat_room room
    JOIN table_assignment own ON own.dining_table_id=room.dining_table_id
    JOIN match_participation mp ON mp.application_id=own.application_id
      AND mp.user_id=own.user_id AND mp.dining_table_id=own.dining_table_id
      AND mp.state='CONFIRMED'
    WHERE own.user_id=:user_id AND own.ended_at IS NULL"""


def ensure_room(connection, table_id, now):
    return connection.execute(
        text("""INSERT INTO chat_room(id,dining_table_id,created_at)
        VALUES(:id,:table_id,:now) ON CONFLICT(dining_table_id)
        DO UPDATE SET dining_table_id=EXCLUDED.dining_table_id RETURNING id"""),
        {"id": uuid.uuid4(), "table_id": table_id, "now": now},
    ).scalar_one()


@router.get("/api/me/rooms")
def rooms(user: Principal = Depends(require_participant)):
    with database_engine().connect() as connection:
        rows = connection.execute(
            text(
                """SELECT room.id,room.dining_table_id,
            t.member_count,s.starts_at,r.name AS region_name """
                + MEMBERSHIP.replace(
                    "    WHERE",
                    "    JOIN dining_table t ON t.id=room.dining_table_id\n"
                    "    JOIN event_slot s ON s.id=t.event_slot_id\n"
                    "    JOIN region r ON r.code=s.region_code\n    WHERE",
                )
                + " ORDER BY s.starts_at,room.id"
            ),
            {"user_id": user.id},
        ).mappings()
        result = [
            {
                "id": str(row["id"]),
                "dining_table_id": str(row["dining_table_id"]),
                "member_count": row["member_count"],
                "starts_at": row["starts_at"].isoformat(),
                "region_name": row["region_name"],
            }
            for row in rows
        ]
    return private_response({"rooms": result})


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    body: str = Field(min_length=1, max_length=2000)


def authorize_room(connection, room_id, user_id):
    if not connection.execute(
        text("SELECT room.id " + MEMBERSHIP + " AND room.id=:room_id"),
        {"room_id": room_id, "user_id": user_id},
    ).first():
        raise HTTPException(404, "room_not_found")


MESSAGE_SELECT = """SELECT m.id,m.kind,m.body,m.created_at,
    p.data->>'display_name' AS display_name FROM chat_message m
    LEFT JOIN participant_profile p ON p.user_id=m.author_id """


def message_json(row):
    return {
        "id": row["id"],
        "kind": row["kind"],
        "body": row["body"],
        "created_at": row["created_at"].isoformat(),
        "author": (
            {"display_name": row["display_name"] or "참가자"} if row["kind"] == "USER" else None
        ),
    }


@router.get("/api/me/rooms/{room_id}/messages")
def messages(
    room_id: uuid.UUID,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    user: Principal = Depends(require_participant),
):
    with database_engine().connect() as connection:
        authorize_room(connection, room_id, user.id)
        rows = connection.execute(
            text(
                MESSAGE_SELECT
                + """WHERE m.room_id=:room_id
            AND m.id>:after_id ORDER BY m.id LIMIT :limit"""
            ),
            {"room_id": room_id, "after_id": after_id, "limit": limit},
        ).mappings()
        result = [message_json(row) for row in rows]
    return private_response(
        {"messages": result, "next_cursor": result[-1]["id"] if result else after_id}
    )


@router.post("/api/me/rooms/{room_id}/messages")
def post_message(
    room_id: uuid.UUID, payload: MessageInput, user: Principal = Depends(require_csrf_participant)
):
    with database_engine().begin() as connection:
        # Every writer locks before the sequence allocates an id, including system posts.
        connection.execute(
            text("SELECT id FROM chat_room WHERE id=:id FOR UPDATE"), {"id": room_id}
        )
        authorize_room(connection, room_id, user.id)
        params = {
            "room_id": room_id,
            "author_id": user.id,
            "request_key": payload.request_key,
            "body": payload.body,
        }
        previous = (
            connection.execute(
                text("""SELECT id,body FROM chat_message
            WHERE room_id=:room_id AND author_id=:author_id AND request_key=:request_key"""),
                params,
            )
            .mappings()
            .first()
        )
        if previous:
            if previous["body"] != payload.body:
                raise HTTPException(409, "request_key_conflict")
            message_id = previous["id"]
        else:
            message_id = connection.execute(
                text("""INSERT INTO chat_message
                (room_id,author_id,kind,request_key,body,created_at)
                VALUES(:room_id,:author_id,'USER',:request_key,:body,CURRENT_TIMESTAMP)
                RETURNING id"""),
                params,
            ).scalar_one()
        row = (
            connection.execute(text(MESSAGE_SELECT + "WHERE m.id=:id"), {"id": message_id})
            .mappings()
            .one()
        )
        result = message_json(row)
    response = private_response({"message": result})
    response.status_code = 200 if previous else 201
    return response


def publish_system_message(connection, room_id, event_key, body, now):
    connection.execute(text("SELECT id FROM chat_room WHERE id=:id FOR UPDATE"), {"id": room_id})
    return connection.execute(
        text("""INSERT INTO chat_message
        (room_id,kind,event_key,body,created_at) VALUES(:room_id,'SYSTEM',:event_key,:body,:now)
        ON CONFLICT(room_id,event_key) DO UPDATE SET event_key=EXCLUDED.event_key RETURNING id"""),
        {"room_id": room_id, "event_key": event_key, "body": body, "now": now},
    ).scalar_one()
