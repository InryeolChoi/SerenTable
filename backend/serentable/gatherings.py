"""Post-confirmation venue allocation and durable, idempotent gathering events."""

import hashlib
import json
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from serentable.auth import (
    Principal,
    private_response,
    require_csrf_operator,
    require_operator,
    require_participant,
)
from serentable.database import database_engine

router = APIRouter()


class InventoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_slot_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(min_length=1, max_length=300)
    map_url: str = Field(max_length=1000)
    price_krw: int = Field(strict=True, ge=10000, le=1000000)
    capacity: int = Field(strict=True, ge=4, le=100)

    @field_validator("map_url")
    @classmethod
    def safe_link(cls, value):
        # Display-only link; the server never fetches this URL.
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("https_map_required")
        if any(ord(c) < 33 for c in value) or "\\" in value:
            raise ValueError("invalid_map_url")
        return value


class FoodApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dining_table_id: uuid.UUID
    food_snapshot: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed_suitable: bool


def inventory_json(row):
    return {
        **{key: str(row[key]) for key in ("id", "event_slot_id")},
        **{key: row[key] for key in ("name", "address", "map_url", "price_krw", "capacity")},
    }


@router.post("/api/admin/venue-inventory", status_code=201)
def create_inventory(payload: InventoryInput, operator: Principal = Depends(require_csrf_operator)):
    with database_engine().begin() as connection:
        if not connection.execute(
            text("SELECT 1 FROM event_slot WHERE id=:id"), {"id": payload.event_slot_id}
        ).scalar():
            raise HTTPException(404, "event_slot_not_found")
        row = (
            connection.execute(
                text("""INSERT INTO venue_inventory
            (id,event_slot_id,name,address,map_url,price_krw,capacity,created_by,created_at)
            VALUES (:id,:event_slot_id,:name,:address,:map_url,:price_krw,:capacity,
                    :operator,CURRENT_TIMESTAMP) RETURNING *"""),
                {**payload.model_dump(), "id": uuid.uuid4(), "operator": operator.id},
            )
            .mappings()
            .one()
        )
        response = private_response({"inventory": inventory_json(row)})
        response.status_code = 201
        return response


@router.get("/api/admin/venue-inventory")
def list_inventory(operator: Principal = Depends(require_operator)):
    with database_engine().connect() as connection:
        rows = connection.execute(text("SELECT * FROM venue_inventory ORDER BY created_at,id"))
        return private_response({"inventory": [inventory_json(row) for row in rows.mappings()]})


def members_for(connection, table_id):
    return (
        connection.execute(
            text("""SELECT a.user_id,p.data FROM table_assignment a
        JOIN match_participation m ON m.application_id=a.application_id AND m.state='CONFIRMED'
        JOIN participant_profile p ON p.user_id=a.user_id
        WHERE a.dining_table_id=:id AND a.ended_at IS NULL ORDER BY a.user_id FOR SHARE OF p"""),
            {"id": table_id},
        )
        .mappings()
        .all()
    )


def food_state(members):
    records = [
        {
            "user_id": str(m["user_id"]),
            **{
                key: m["data"].get(key, {"status": "unknown"})
                for key in ("food_restrictions", "allergies")
            },
        }
        for m in members
    ]
    digest = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    clear = bool(records) and all(
        item[key].get("status") == "none"
        for item in records
        for key in ("food_restrictions", "allergies")
    )
    return digest, clear, records


@router.get("/api/admin/gathering-tables")
def admin_tables(operator: Principal = Depends(require_operator)):
    with database_engine().connect() as connection:
        tables = connection.execute(text("SELECT id,event_slot_id FROM dining_table ORDER BY id"))
        result = []
        for table in tables.mappings().all():
            digest, clear, records = food_state(members_for(connection, table["id"]))
            result.append(
                {
                    "id": str(table["id"]),
                    "event_slot_id": str(table["event_slot_id"]),
                    "food_snapshot": digest,
                    "food_clear": clear,
                    "conditions": records,
                }
            )
        return private_response({"tables": result})


@router.post("/api/admin/venue-inventory/{inventory_id}/food-approvals")
def approve_food(
    inventory_id: uuid.UUID,
    payload: FoodApprovalInput,
    operator: Principal = Depends(require_csrf_operator),
):
    if not payload.confirmed_suitable:
        raise HTTPException(422, "explicit_suitability_required")
    with database_engine().begin() as connection:
        table = (
            connection.execute(
                text("SELECT * FROM dining_table WHERE id=:id FOR UPDATE"),
                {"id": payload.dining_table_id},
            )
            .mappings()
            .first()
        )
        inventory = (
            connection.execute(
                text("SELECT * FROM venue_inventory WHERE id=:id"), {"id": inventory_id}
            )
            .mappings()
            .first()
        )
        if not table or not inventory or table["event_slot_id"] != inventory["event_slot_id"]:
            raise HTTPException(404, "inventory_table_not_found")
        digest, _, _ = food_state(members_for(connection, table["id"]))
        if digest != payload.food_snapshot:
            raise HTTPException(409, "food_conditions_changed")
        connection.execute(
            text("""INSERT INTO venue_food_approval
            (inventory_id,dining_table_id,food_snapshot,reviewed_by,created_at)
            VALUES (:inventory,:table,:snapshot,:operator,CURRENT_TIMESTAMP)
            ON CONFLICT DO NOTHING"""),
            {
                "inventory": inventory_id,
                "table": table["id"],
                "snapshot": digest,
                "operator": operator.id,
            },
        )
        return private_response({"approved": True})


@router.get("/api/me/gatherings")
def my_gatherings(user: Principal = Depends(require_participant)):
    with database_engine().connect() as connection:
        rows = (
            connection.execute(
                text("""SELECT t.id,s.starts_at,s.ends_at,r.name AS region_name,
            c.id AS room_id,v.name,v.address,v.map_url,v.price_krw,a.reservation_name
            FROM table_assignment ta JOIN match_participation m
              ON m.application_id=ta.application_id AND m.state='CONFIRMED'
            JOIN dining_table t ON t.id=ta.dining_table_id
            JOIN event_slot s ON s.id=t.event_slot_id JOIN region r ON r.code=s.region_code
            LEFT JOIN chat_room c ON c.dining_table_id=t.id
            LEFT JOIN venue_allocation a ON a.dining_table_id=t.id
            LEFT JOIN venue_inventory v ON v.id=a.inventory_id
            WHERE ta.user_id=:user AND ta.ended_at IS NULL ORDER BY s.starts_at,t.id"""),
                {"user": user.id},
            )
            .mappings()
            .all()
        )
        return private_response(
            {
                "gatherings": [
                    {
                        "id": str(row["id"]),
                        "starts_at": row["starts_at"].isoformat(),
                        "ends_at": row["ends_at"].isoformat(),
                        "region_name": row["region_name"],
                        "room_id": str(row["room_id"]) if row["room_id"] else None,
                        "venue_state": "ASSIGNED" if row["name"] else "PENDING_OPERATOR",
                        "venue": {
                            key: row[key]
                            for key in (
                                "name",
                                "address",
                                "map_url",
                                "price_krw",
                                "reservation_name",
                            )
                        }
                        if row["name"]
                        else None,
                    }
                    for row in rows
                ]
            }
        )


def emit(connection, table_id, room_id, members, event, body, now):
    from serentable.chat import publish_system_message
    from serentable.notifications import enqueue_notification

    key = f"table:{table_id}:{event}"
    publish_system_message(connection, room_id, key, body, now)
    for member in members:
        enqueue_notification(
            connection,
            member["user_id"],
            key,
            event,
            "우연한 식탁 모임 안내",
            body,
            "/participant/gatherings",
            now,
        )


def allocate_venue(connection, table, members, now):
    existing = (
        connection.execute(
            text("""SELECT v.*,a.reservation_name FROM venue_allocation a
        JOIN venue_inventory v ON v.id=a.inventory_id WHERE a.dining_table_id=:id"""),
            {"id": table["id"]},
        )
        .mappings()
        .first()
    )
    if existing:
        return existing
    digest, clear, _ = food_state(members)
    inventory = (
        connection.execute(
            text("""SELECT v.* FROM venue_inventory v
        WHERE v.event_slot_id=:slot AND v.active AND v.capacity>=:count
        AND NOT EXISTS (SELECT 1 FROM venue_allocation a WHERE a.inventory_id=v.id)
        ORDER BY v.created_at,v.id FOR UPDATE OF v"""),
            {"slot": table["event_slot_id"], "count": table["member_count"]},
        )
        .mappings()
        .all()
    )
    for venue in inventory:
        band = (
            "10000_20000"
            if venue["price_krw"] < 20000
            else "20000_30000"
            if venue["price_krw"] < 30000
            else "30000_plus"
        )
        if not all(band in m["data"].get("meal_budget_bands", []) for m in members):
            continue
        if (
            not clear
            and not connection.execute(
                text("""SELECT 1 FROM venue_food_approval
            WHERE inventory_id=:inventory AND dining_table_id=:table AND food_snapshot=:digest"""),
                {"inventory": venue["id"], "table": table["id"], "digest": digest},
            ).scalar()
        ):
            continue
        reservation = f"우연한식탁-{str(table['id'])[:8]}"
        connection.execute(
            text("""INSERT INTO venue_allocation
            (id,dining_table_id,inventory_id,reservation_name,created_at)
            VALUES (:id,:table,:inventory,:name,:now)"""),
            {
                "id": uuid.uuid4(),
                "table": table["id"],
                "inventory": venue["id"],
                "name": reservation,
                "now": now,
            },
        )
        return {**venue, "reservation_name": reservation}
    return None


def process_table(connection, table_id):
    from serentable.chat import ensure_room

    table = (
        connection.execute(
            text("""SELECT t.*,s.starts_at,s.ends_at FROM dining_table t
        JOIN event_slot s ON s.id=t.event_slot_id WHERE t.id=:id FOR UPDATE OF t"""),
            {"id": table_id},
        )
        .mappings()
        .one()
    )
    now = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
    # Historical tables remain untouched. No retroactive notifications after the event.
    if now >= table["ends_at"]:
        return
    members = members_for(connection, table_id)
    if len(members) != table["member_count"]:
        return
    room = ensure_room(connection, table_id, now)
    emit(
        connection,
        table_id,
        room,
        members,
        "CONFIRMED",
        "모임이 확정되었습니다. 모임 안내를 확인해 주세요.",
        now,
    )
    venue = allocate_venue(connection, table, members, now)
    exception_key = f"table:{table_id}:venue"
    if venue:
        connection.execute(
            text("""UPDATE gathering_exception SET state='RESOLVED',updated_at=:now
            WHERE event_key=:key AND state='OPEN'"""),
            {"key": exception_key, "now": now},
        )
        body = (
            f"식당: {venue['name']} · 주소: {venue['address']}"
            f" · 예약명: {venue['reservation_name']}"
            f" · 예상 식비: {venue['price_krw']:,}원."
            " 지도와 모임 시각은 모임 안내에서 확인해 주세요."
        )
        emit(connection, table_id, room, members, "VENUE_ASSIGNED", body, now)
    else:
        connection.execute(
            text("""INSERT INTO gathering_exception
            (id,dining_table_id,event_key,kind,state,reason_code,created_at,updated_at)
            VALUES (:id,:table,:key,'VENUE','OPEN','no_verified_inventory',:now,:now)
            ON CONFLICT (event_key) DO NOTHING"""),
            {"id": uuid.uuid4(), "table": table_id, "key": exception_key, "now": now},
        )
        emit(
            connection,
            table_id,
            room,
            members,
            "VENUE_PENDING",
            "식당 배정은 운영자 확인 중입니다. 확정된 모임과 대화방은 유지됩니다.",
            now,
        )
    if now >= table["starts_at"]:
        interests = sorted({i for m in members for i in m["data"].get("interests", [])})
        label = interests[0] if interests else "새로운 경험"
        body = (
            f"오늘의 대화 주제 ① {label}에 관심을 갖게 된 계기는 무엇인가요? "
            f"② {label}와 관련해 추천하고 싶은 경험은? "
            "③ 요즘 새로 시도해 보고 싶은 활동은? "
            "아이스브레이킹: 서로 표시명과 오늘 기대하는 한 가지를 돌아가며 소개해 주세요."
        )
        emit(connection, table_id, room, members, "START_CONTENT", body, now)
    elif (table["starts_at"] - now).total_seconds() <= 86400:
        emit(
            connection,
            table_id,
            room,
            members,
            "REMINDER",
            "모임이 하루 안에 시작합니다. 모임 시각과 식당 배정 상태를 확인해 주세요.",
            now,
        )


def run_gathering_jobs():
    with database_engine().connect() as connection:
        ids = (
            connection.execute(
                text("""SELECT t.id FROM dining_table t JOIN event_slot s
            ON s.id=t.event_slot_id WHERE s.ends_at>clock_timestamp() ORDER BY t.id""")
            )
            .scalars()
            .all()
        )
    for table_id in ids:
        # Shared job lock serializes inventory consumption; each table remains atomic.
        with database_engine().begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(7081707)"))
            process_table(connection, table_id)
