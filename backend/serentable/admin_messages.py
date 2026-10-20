"""PRD §11·§17 operator views: table detail and automatic message templates/history.

Read-only. Messages are produced by the worker and by participant state changes; there is
no manual send, edit or approval here (§7.3: the normal flow needs no operator action).
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text

from serentable.auth import Principal, private_response, require_operator
from serentable.clock import iso
from serentable.database import database_engine

router = APIRouter()

# Message bodies are written in code (gatherings.py, feedback.py, participant_notices.py);
# this is the operator-facing catalogue of when each one goes out and where.
TEMPLATES = [
    ("APPLICATION_SUBMITTED", "신청 완료·결제 대기", "신청 직후", "앱 알림·푸시"),
    ("PAYMENT_COMPLETED", "결제 완료", "모의 결제 완료 직후", "앱 알림·푸시"),
    ("MATCHING_FAILED", "매칭 실패", "자동 매칭에서 배정되지 않았을 때", "앱 알림·푸시"),
    ("SCHEDULE_MOVED", "일정 이동 완료", "참가자가 대체 일정을 고른 직후", "앱 알림·푸시"),
    ("PASS_HELD", "이용권 보관", "참가자가 보관을 고른 직후", "앱 알림·푸시"),
    ("REFUND_COMPLETED", "환불 완료", "모의 환불 완료 직후(재시도 포함)", "앱 알림·푸시"),
    ("REFUND_FAILED", "환불 처리 실패", "모의 환불 저장 실패 시", "앱 알림·푸시"),
    ("CONFIRMED", "매칭 확정", "테이블 확정 후 작업 실행기", "단체방·앱 알림·푸시"),
    ("VENUE_ASSIGNED", "식당 배정", "가상 재고 배정 시", "단체방·앱 알림·푸시"),
    ("VENUE_PENDING", "식당 확인 중", "배정 가능한 재고가 없을 때", "단체방·앱 알림·푸시"),
    ("REMINDER", "행사 1일 전 리마인드", "시작 24시간 전부터", "단체방·앱 알림·푸시"),
    ("START_CONTENT", "대화 주제", "모임 시작 시각", "단체방·앱 알림·푸시"),
    ("FEEDBACK_REMINDER", "후기 요청", "종료 24시간 후 미작성자", "앱 알림·푸시"),
]

PUSH_STATE = """CASE WHEN EXISTS(SELECT 1 FROM push_delivery d WHERE d.notification_id=n.id
    AND d.state='SENT') THEN 'accepted' WHEN EXISTS(SELECT 1 FROM push_delivery d
    WHERE d.notification_id=n.id AND d.state='PENDING') THEN 'pending'
    WHEN EXISTS(SELECT 1 FROM push_delivery d WHERE d.notification_id=n.id
    AND d.state='FAILED') THEN 'failed' WHEN EXISTS(SELECT 1 FROM push_delivery d
    WHERE d.notification_id=n.id) THEN 'unavailable' ELSE 'not_subscribed' END"""


@router.get("/api/admin/messages")
def messages(operator: Principal = Depends(require_operator)):
    with database_engine().connect() as connection:
        rows = (
            connection.execute(
                text(f"""SELECT n.id,n.kind,n.title,n.body,n.created_at,n.read_at,
            u.login_id,{PUSH_STATE} AS push_status
            FROM app_notification n JOIN app_user u ON u.id=n.user_id
            ORDER BY n.created_at DESC,n.id LIMIT 200""")
            )
            .mappings()
            .all()
        )
    return private_response(
        {
            "templates": [
                {"kind": kind, "name": name, "trigger": trigger, "channels": channels}
                for kind, name, trigger, channels in TEMPLATES
            ],
            "history": [
                {
                    "id": str(row["id"]),
                    "kind": row["kind"],
                    "title": row["title"],
                    "body": row["body"],
                    "login_id": row["login_id"],
                    "created_at": iso(row["created_at"]),
                    "read": row["read_at"] is not None,
                    "push_status": row["push_status"],
                }
                for row in rows
            ],
        }
    )


@router.get("/api/admin/table-details")
def table_details(operator: Principal = Depends(require_operator)):
    with database_engine().connect() as connection:
        tables = (
            connection.execute(
                text("""SELECT t.id,t.member_count,s.starts_at,r.name AS region_name,
            vi.name AS venue_name,va.reservation_name,c.id AS room_id,
            (SELECT count(*) FROM chat_message m WHERE m.room_id=c.id) AS message_count
            FROM dining_table t JOIN event_slot s ON s.id=t.event_slot_id
            JOIN region r ON r.code=s.region_code
            LEFT JOIN venue_allocation va ON va.dining_table_id=t.id
            LEFT JOIN venue_inventory vi ON vi.id=va.inventory_id
            LEFT JOIN chat_room c ON c.dining_table_id=t.id
            WHERE EXISTS(SELECT 1 FROM table_assignment a
                WHERE a.dining_table_id=t.id AND a.ended_at IS NULL)
            ORDER BY s.starts_at DESC,t.id LIMIT 100""")
            )
            .mappings()
            .all()
        )
        result = []
        for table in tables:
            members = (
                connection.execute(
                    text("""SELECT u.login_id FROM table_assignment a
                JOIN app_user u ON u.id=a.user_id
                WHERE a.dining_table_id=:id AND a.ended_at IS NULL ORDER BY u.login_id"""),
                    {"id": table["id"]},
                )
                .scalars()
                .all()
            )
            notices = dict(
                connection.execute(
                    text(f"""SELECT push_status,count(*) FROM (SELECT {PUSH_STATE} AS push_status
                FROM app_notification n WHERE n.event_key LIKE :table_key
                OR n.event_key=:feedback_key) q GROUP BY push_status"""),
                    {
                        "table_key": f"table:{table['id']}:%",
                        "feedback_key": f"feedback-reminder:{table['id']}",
                    },
                ).all()
            )
            result.append(
                {
                    "id": str(table["id"]),
                    "starts_at": iso(table["starts_at"]),
                    "region_name": table["region_name"],
                    "member_count": table["member_count"],
                    "members": members,
                    "venue": {
                        "name": table["venue_name"],
                        "reservation_name": table["reservation_name"],
                    }
                    if table["venue_name"]
                    else None,
                    "room_id": str(table["room_id"]) if table["room_id"] else None,
                    "message_count": table["message_count"],
                    "notices": notices,
                }
            )
    return private_response({"tables": result})
