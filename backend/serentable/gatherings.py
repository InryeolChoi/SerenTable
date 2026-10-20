"""Post-confirmation venue allocation and durable, idempotent gathering events."""

import hashlib
import json
import uuid
from collections import Counter
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from serentable.audit import record_audit
from serentable.auth import (
    Principal,
    private_response,
    require_csrf_operator,
    require_operator,
    require_participant,
)
from serentable.clock import SEOUL
from serentable.database import database_engine
from serentable.profile import OPTIONS

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
        record_audit(
            connection,
            operator.id,
            "venue_inventory.create",
            "venue_inventory",
            row["id"],
            after={
                "event_slot_id": str(row["event_slot_id"]),
                **{key: row[key] for key in ("name", "price_krw", "capacity")},
            },
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
            "meal_budget_bands": sorted(set(m["data"].get("meal_budget_bands", []))),
            **{
                key: m["data"].get(key, {"status": "unknown"})
                for key in ("food_restrictions", "allergies")
            },
        }
        for m in members
    ]
    digest = hashlib.sha256(
        json.dumps({"version": 1, "conditions": records}, sort_keys=True).encode()
    ).hexdigest()
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
            allocation = (
                connection.execute(
                    text("""SELECT inventory_id,reviewed_conditions_snapshot
                FROM venue_allocation WHERE dining_table_id=:id"""),
                    {"id": table["id"]},
                )
                .mappings()
                .first()
            )
            open_review = connection.execute(
                text("""SELECT 1 FROM gathering_exception
                WHERE event_key=:key AND state='OPEN'"""),
                {"key": f"table:{table['id']}:venue-conditions"},
            ).scalar()
            result.append(
                {
                    "id": str(table["id"]),
                    "event_slot_id": str(table["event_slot_id"]),
                    "food_snapshot": digest,
                    "food_clear": clear,
                    "allocated_inventory_id": str(allocation["inventory_id"])
                    if allocation
                    else None,
                    "review_required": bool(
                        allocation
                        and (allocation["reviewed_conditions_snapshot"] != digest or open_review)
                    ),
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
        members = members_for(connection, table["id"])
        digest, _, _ = food_state(members)
        allocation = (
            connection.execute(
                text("""SELECT * FROM venue_allocation
            WHERE dining_table_id=:id"""),
                {"id": table["id"]},
            )
            .mappings()
            .first()
        )
        if allocation and allocation["inventory_id"] != inventory_id:
            raise HTTPException(409, "allocated_inventory_mismatch")
        if not members or len(members) > inventory["capacity"]:
            raise HTTPException(409, "venue_capacity_mismatch")
        if not price_suitable(inventory["price_krw"], members):
            raise HTTPException(409, "venue_budget_mismatch")
        if digest != payload.food_snapshot:
            raise HTTPException(409, "food_conditions_changed")
        inserted = connection.execute(
            text("""INSERT INTO venue_food_approval
            (inventory_id,dining_table_id,food_snapshot,reviewed_by,created_at)
            VALUES (:inventory,:table,:snapshot,:operator,CURRENT_TIMESTAMP)
            ON CONFLICT DO NOTHING RETURNING 1"""),
            {
                "inventory": inventory_id,
                "table": table["id"],
                "snapshot": digest,
                "operator": operator.id,
            },
        ).scalar()
        reviewed = resolved = False
        if allocation:
            reviewed = bool(
                connection.execute(
                    text("""UPDATE venue_allocation
                SET reviewed_conditions_snapshot=:digest WHERE dining_table_id=:id
                AND reviewed_conditions_snapshot IS DISTINCT FROM :digest RETURNING 1"""),
                    {"id": table["id"], "digest": digest},
                ).scalar()
            )
            resolved = bool(
                connection.execute(
                    text("""UPDATE gathering_exception SET state='RESOLVED',
                updated_at=clock_timestamp(),resolved_by=:operator,
                resolution_note='current_conditions_verified'
                WHERE event_key=:key AND state='OPEN' RETURNING 1"""),
                    {"key": f"table:{table['id']}:venue-conditions", "operator": operator.id},
                ).scalar()
            )
        if inserted or reviewed or resolved:
            # Only the snapshot digest is kept; members' food conditions stay out of the trail.
            record_audit(
                connection,
                operator.id,
                "venue_food.approve",
                "dining_table",
                table["id"],
                after={
                    "inventory_id": str(inventory_id),
                    "food_snapshot": digest,
                    "confirmed_suitable": True,
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


def price_suitable(price, members):
    band = "10000_20000" if price < 20000 else "20000_30000" if price < 30000 else "30000_plus"
    return all(band in m["data"].get("meal_budget_bands", []) for m in members)


def allocate_venue(connection, table, members, now):
    existing = (
        connection.execute(
            text("""SELECT v.*,a.reservation_name,a.reviewed_conditions_snapshot
        FROM venue_allocation a
        JOIN venue_inventory v ON v.id=a.inventory_id WHERE a.dining_table_id=:id"""),
            {"id": table["id"]},
        )
        .mappings()
        .first()
    )
    digest, clear, _ = food_state(members)
    if existing:
        if existing["reviewed_conditions_snapshot"] != digest:
            connection.execute(
                text("""INSERT INTO gathering_exception
                (id,dining_table_id,event_key,kind,state,reason_code,created_at,updated_at)
                VALUES (:id,:table,:key,'VENUE_CONDITIONS','OPEN',:reason,:now,:now)
                ON CONFLICT(event_key) DO UPDATE SET state='OPEN',reason_code=EXCLUDED.reason_code,
                updated_at=EXCLUDED.updated_at,resolved_by=NULL,resolution_note=NULL
                WHERE gathering_exception.state='RESOLVED'"""),
                {
                    "id": uuid.uuid4(),
                    "table": table["id"],
                    "key": f"table:{table['id']}:venue-conditions",
                    "now": now,
                    "reason": "allocated_conditions_changed"
                    if existing["reviewed_conditions_snapshot"]
                    else "condition_baseline_missing",
                },
            )
        return existing
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
        if not price_suitable(venue["price_krw"], members):
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
            (id,dining_table_id,inventory_id,reservation_name,created_at,reviewed_conditions_snapshot)
            VALUES (:id,:table,:inventory,:name,:now,:digest)"""),
            {
                "id": uuid.uuid4(),
                "table": table["id"],
                "inventory": venue["id"],
                "name": reservation,
                "digest": digest,
                "now": now,
            },
        )
        return {**venue, "reservation_name": reservation}
    return None


def reminder_body(table, venue):
    start = table["starts_at"].astimezone(SEOUL).strftime("%Y-%m-%d %H:%M")
    place = (
        f"식당: {venue['name']} · 주소: {venue['address']} · 예약명: {venue['reservation_name']}. "
        if venue
        else "식당·장소·예약명: 운영자 확인 중(미배정). 배정되면 별도 안내합니다. "
    )
    return (
        f"모임이 하루 안에 시작합니다. 집합 시각: {start} (서울). "
        + place
        + "환불 규정: 모임 진행 2일 전(현행 기준 화요일 24:00) 이후에는 환불할 수 없습니다. "
        "당일 취소·노쇼 정책: 확정 후에는 앱에서 취소할 수 없으며 당일 불참은 노쇼로 "
        "처리됩니다. 종료 시각까지 체크인하지 않으면 노쇼 후보가 되고 운영자가 확인해 "
        "확정하거나 사유를 인정합니다. 확정 노쇼는 경고·참가 제한 대상이 될 수 있습니다."
    )


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
        "모임이 확정되었습니다. 모임 시각·장소는 모임 안내에서 확인해 주세요. "
        "취소 가능 여부는 신청 현황에서 확인하세요. 시스템 매칭 실패의 미사용 1회권은 "
        "전액 모의 환불할 수 있으며 멤버십 금액 환불은 지원하지 않습니다.",
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
        interests = Counter(i for m in members for i in set(m["data"].get("interests", [])))
        shared = sorted(
            (i for i, count in interests.items() if count >= 2), key=lambda i: (-interests[i], i)
        )
        label = OPTIONS["interests"].get(shared[0], "새로운 경험") if shared else "새로운 경험"
        traits = {t for m in members for t in m["data"].get("self_traits", [])}
        style = "차분하게 서로의 이야기를 듣고" if "listener" in traits else "가볍게 돌아가며"
        body = (
            f"오늘의 대화 주제 ① {label}에 관심을 갖게 된 계기는 무엇인가요? "
            f"② 관심 주제인 {label} 관련해서 추천하고 싶은 경험은? "
            f"③ {style} 관심 주제를 함께 즐길 방법을 이야기해 보세요. "
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
            reminder_body(table, venue),
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
