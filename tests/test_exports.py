"""Work #9 ticket D: operator CSV exports through HTTP and the real isolated PostgreSQL.

Expected rows come from the small hand-built table below, written as literals. Ids and
submission times are the values the participants' own API returned, not recomputed here.
"""

import csv
import io
import time
import uuid
from contextlib import ExitStack
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.main import app
from sqlalchemy import text
from support import login, send, truncate
from test_applications import COMPLETE_PROFILE
from test_matching_runner import apply_and_pay, due_slot, prepare

# Four paid members whose display names each start with a formula trigger, plus one
# unpaid applicant with an ordinary name.
NAMES = ["=SUM(1)", "+82 식탁", "-하이픈", "@멘션"]
UNPAID_NAME = "보통 이름"
UNPAID_LOGIN = "participant-d-unpaid"
LOGINS = [f"participant-0{index}" for index in range(1, 5)] + [UNPAID_LOGIN]
SAFE_FOOD = {"food_restrictions": {"status": "none"}, "allergies": {"status": "none"}}
APPLICATION_HEADER = ["신청 ID", "표시명", "신청 상태", "결제 상태", "매칭 상태", "제출 시각"]


@pytest.fixture
def slot(seeded_database):
    truncate("event_slot, participant_profile, consent_record, app_notification, operator_audit")
    # The demo seed has four participants; a fifth synthetic one reuses the demo hash.
    with database_engine().begin() as connection:
        connection.execute(
            text(f"""INSERT INTO app_user(id,login_id,password_hash,role,active)
            SELECT gen_random_uuid(),'{UNPAID_LOGIN}',password_hash,role,true
            FROM app_user WHERE login_id='participant-01' ON CONFLICT(login_id) DO NOTHING""")
        )
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(5)]
        login(operator, "operator")
        names = [*NAMES, UNPAID_NAME]
        for member, login_id, name in zip(members, LOGINS, names, strict=True):
            prepare(member, login_id)
            profile = {**COMPLETE_PROFILE, **SAFE_FOOD, "display_name": name}
            assert send(member, "PUT", "/api/me/profile", profile).status_code == 200
        slot_id = due_slot(operator, close_in=4)
        applications = [apply_and_pay(member, slot_id) for member in members[:4]]
        applications.append(apply_and_pay(members[4], slot_id, paid=False))
        yield {
            "id": slot_id,
            "operator": operator,
            "members": members,
            "applications": applications,
        }


def download(client, name, slot_id):
    return client.get(f"/api/admin/exports/{name}", params={"event_slot_id": slot_id})


def parse(response):
    body = response.content
    assert body.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(io.StringIO(body[3:].decode("utf-8"), newline="")))


def submitted_at(member, application_id):
    mine = member.get("/api/me/applications").json()["applications"]
    (found,) = [a for a in mine if a["id"] == application_id]
    return datetime.fromisoformat(found["submitted_at"]).replace(microsecond=0)


def test_applications_csv_lists_each_applicant_with_guarded_cells(slot):
    response = download(slot["operator"], "applications.csv", slot["id"])
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="applications-{slot["id"]}.csv"'
    )
    rows = parse(response)
    assert rows[0] == APPLICATION_HEADER
    expected = [
        ["'=SUM(1)", "SUBMITTED", "PAID", ""],
        ["'+82 식탁", "SUBMITTED", "PAID", ""],
        ["'-하이픈", "SUBMITTED", "PAID", ""],
        ["'@멘션", "SUBMITTED", "PAID", ""],
        ["보통 이름", "SUBMITTED", "", ""],
    ]
    assert [row[1:5] for row in rows[1:]] == expected
    assert [row[0] for row in rows[1:]] == slot["applications"]
    for row, member, application_id in zip(
        rows[1:], slot["members"], slot["applications"], strict=True
    ):
        assert datetime.fromisoformat(row[5]) == submitted_at(member, application_id)
    for private in ("010-0000-0000", "synthetic_demo", "합성 이름"):
        assert private not in response.text


TABLE_HEADER = ["테이블 ID", "점수", "인원", "표시명 목록", "식당명", "체크인 수"]


def match_and_seat(slot):
    """Matching, venue allocation and one check-in through the real runner and API."""
    from serentable.gatherings import run_gathering_jobs
    from serentable.matching import run_due_matches

    venue = {
        "event_slot_id": slot["id"],
        "name": "합성 식당",
        "address": "합성 주소",
        "map_url": "https://map.naver.com/",
        "price_krw": 15000,
        "capacity": 6,
    }
    operator = slot["operator"]
    assert send(operator, "POST", "/api/admin/venue-inventory", venue).status_code == 201
    time.sleep(4.6)
    assert run_due_matches()[0]["seated_count"] == 4
    run_gathering_jobs()
    # Fixture clock: open the check-in window for the isolated slot (no app overrides).
    with database_engine().begin() as connection:
        connection.execute(
            text("""UPDATE event_slot SET closes_at=now()-interval '2 days',
            matches_at=now()-interval '1 day', starts_at=now()+interval '10 minutes',
            ends_at=now()+interval '130 minutes' WHERE id=:slot"""),
            {"slot": slot["id"]},
        )
    gathering = slot["members"][1].get("/api/me/gatherings").json()["gatherings"][0]
    assert gathering["venue_state"] == "ASSIGNED"
    table_id = gathering["id"]
    path = f"/api/me/tables/{table_id}/check-in"
    assert send(slot["members"][1], "POST", path).status_code == 201
    return table_id


def test_tables_csv_lists_each_confirmed_table_with_score_venue_and_check_ins(slot):
    table_id = match_and_seat(slot)
    response = download(slot["operator"], "tables.csv", slot["id"])
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        f'attachment; filename="tables-{slot["id"]}.csv"'
    )
    # COMPLETE_PROFILE for all four: score 1100/13 = 84.62 (see test_matching_runner).
    # Names are listed in code-point order; only the leading cell character is guarded.
    assert parse(response) == [
        TABLE_HEADER,
        [table_id, "84.62", "4", "'+82 식탁, -하이픈, =SUM(1), @멘션", "합성 식당", "1"],
    ]
    for private in ("010-0000-0000", "synthetic_demo", "합성 이름", "합성 주소", "우연한식탁-"):
        assert private not in response.text
    # After matching the applications export shows the matching axis too.
    rows = parse(download(slot["operator"], "applications.csv", slot["id"]))
    assert [row[4] for row in rows[1:]] == ["CONFIRMED"] * 4 + [""]


def export_audit():
    # Restrict this export test to export actions; fixture creation is audited too.
    with database_engine().connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text("""SELECT a.action, a.target_type, a.target_id, a.after_state, u.login_id
                FROM operator_audit a JOIN app_user u ON u.id = a.actor_id
                WHERE a.action = 'export' ORDER BY a.id""")
            ).all()
        ]


def test_only_operators_export_known_slots_and_each_export_is_audited(slot):
    member, operator = slot["members"][0], slot["operator"]
    for name in ("applications.csv", "tables.csv"):
        assert download(member, name, slot["id"]).status_code == 403
        with TestClient(app) as anonymous:
            assert download(anonymous, name, slot["id"]).status_code == 401
        assert download(operator, name, str(uuid.uuid4())).status_code == 404
        assert operator.get(f"/api/admin/exports/{name}").status_code == 422
    assert operator.get("/api/admin/exports/payments.csv").status_code == 404
    # Refused and unknown requests leave no trail.
    assert export_audit() == []
    assert download(operator, "applications.csv", slot["id"]).status_code == 200
    assert download(operator, "tables.csv", slot["id"]).status_code == 200
    assert download(operator, "applications.csv", slot["id"]).status_code == 200
    assert export_audit() == [
        ("export", "event_slot", slot["id"], {"file": "applications", "rows": 5}, "operator"),
        ("export", "event_slot", slot["id"], {"file": "tables", "rows": 0}, "operator"),
        ("export", "event_slot", slot["id"], {"file": "applications", "rows": 5}, "operator"),
    ]


@pytest.mark.parametrize("prefix", ["\t", "\r"])
def test_csv_guards_legacy_control_prefix_cells(slot, prefix):
    # Legacy/imported data can predate the profile API's whitespace trimming.
    unsafe_name = prefix + "=SUM(1)"
    with database_engine().begin() as connection:
        connection.execute(
            text("""UPDATE participant_profile SET data=jsonb_set(data,'{display_name}',
                to_jsonb(CAST(:name AS text))) WHERE user_id=(
                SELECT id FROM app_user WHERE login_id='participant-01')"""),
            {"name": unsafe_name},
        )
    rows = parse(download(slot["operator"], "applications.csv", slot["id"]))
    assert rows[1][1] == "'" + unsafe_name


def test_tables_csv_counts_only_current_confirmed_assignments(slot):
    table_id = match_and_seat(slot)
    # Simulate ended, no-longer-confirmed and moved historical assignments.
    # Keep the original table's recorded match-time size (4) unchanged.
    with database_engine().begin() as connection:
        connection.execute(
            text("UPDATE table_assignment SET ended_at=now() WHERE application_id=:app"),
            {"app": slot["applications"][0]},
        )
        connection.execute(
            text("""UPDATE match_participation SET state='NO_MATCH',dining_table_id=NULL
                WHERE application_id=:app"""),
            {"app": slot["applications"][1]},
        )
        other_table = str(uuid.uuid4())
        connection.execute(
            text("""INSERT INTO dining_table(id,match_run_id,event_slot_id,member_count,score)
                SELECT :other,match_run_id,event_slot_id,4,score FROM dining_table
                WHERE id=:original"""),
            {"other": other_table, "original": table_id},
        )
        connection.execute(
            text("UPDATE match_participation SET dining_table_id=:other WHERE application_id=:app"),
            {"other": other_table, "app": slot["applications"][2]},
        )
    rows = parse(download(slot["operator"], "tables.csv", slot["id"]))
    original = next(row for row in rows[1:] if row[0] == table_id)
    assert original[2:4] == ["1", "'@멘션"]
    empty = next(row for row in rows[1:] if row[0] == other_table)
    assert empty[2:4] == ["0", ""]
