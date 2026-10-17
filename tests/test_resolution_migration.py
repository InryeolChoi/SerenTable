"""Upgrade pre-resolution grants without changing their purchase or usage history."""

import subprocess
import sys
import uuid

from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.main import app
from sqlalchemy import text
from support import login
from test_synthetic_roster_seed import roster_database  # noqa: F401


def test_existing_single_grants_and_confirmed_usage_survive_additive_upgrade(request):
    request.getfixturevalue("roster_database")
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0009_matching_score"], check=True
    )
    applications = [uuid.uuid4(), uuid.uuid4()]
    payments = [uuid.uuid4(), uuid.uuid4()]
    rights = [uuid.uuid4(), uuid.uuid4()]
    slot, run, table = [uuid.uuid4() for _ in range(3)]
    with database_engine().begin() as connection:
        user = connection.execute(
            text("SELECT id FROM app_user WHERE login_id='participant-01'")
        ).scalar_one()
        # DRAFT is sufficient for the migration's persisted purchase/ownership shape;
        # this fixture does not claim an eligible application or rerun any old matching.
        for application, payment, right in zip(applications, payments, rights, strict=True):
            connection.execute(
                text("""INSERT INTO application(id,user_id,request_key,state)
                VALUES(:id,:user,:key,'DRAFT')"""),
                {"id": application, "user": user, "key": uuid.uuid4()},
            )
            connection.execute(
                text("""INSERT INTO payment(id,application_id,user_id,request_key,
                state,product_code,product_name,product_kind,product_version,amount_krw,
                policy_version,simulated_failure,requested_at,completed_at)
                VALUES(:id,:app,:user,:key,'PAID','single','1회권','SINGLE','legacy',9900,
                'legacy',false,now(),now())"""),
                {"id": payment, "app": application, "user": user, "key": uuid.uuid4()},
            )
            connection.execute(
                text("""INSERT INTO entitlement(id,user_id,payment_id,kind,
                application_id,starts_at,policy_version)
                VALUES(:id,:user,:payment,'SINGLE',:app,now(),'legacy')"""),
                {"id": right, "user": user, "payment": payment, "app": application},
            )
        connection.execute(
            text("""INSERT INTO event_slot(id,region_code,starts_at,ends_at,
            closes_at,matches_at,capacity,created_by)
            VALUES(:id,'hongdae',now()+interval '7 days',now()+interval '7 days 2 hours',
            now()+interval '1 day',now()+interval '1 day 1 second',12,
            (SELECT id FROM app_user WHERE login_id='operator'))"""),
            {"id": slot},
        )
        connection.execute(
            text("""INSERT INTO match_run(id,event_slot_id,attempt,state,
            algorithm_version,rule_version,seated_count,started_at,finished_at)
            VALUES(:id,:slot,1,'SUCCEEDED','legacy','legacy',4,now(),now())"""),
            {"id": run, "slot": slot},
        )
        connection.execute(
            text("""INSERT INTO dining_table(id,match_run_id,event_slot_id,member_count)
            VALUES(:id,:run,:slot,4)"""),
            {"id": table, "run": run, "slot": slot},
        )
        connection.execute(
            text("""INSERT INTO table_assignment(id,dining_table_id,event_slot_id,
            application_id,user_id) VALUES(:id,:table,:slot,:app,:user)"""),
            {
                "id": uuid.uuid4(),
                "table": table,
                "slot": slot,
                "app": applications[1],
                "user": user,
            },
        )
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    with TestClient(app) as owner:
        login(owner, "participant-01")
        actual = {r["id"]: r for r in owner.get("/api/me/entitlements").json()["entitlements"]}
        assert actual[str(rights[0])]["state"] == "HELD"
        assert actual[str(rights[1])]["state"] == "USED"
        for application, payment, right in zip(applications, payments, rights, strict=True):
            assert actual[str(right)]["application_id"] == str(application)
            assert actual[str(right)]["reserved_application_id"] == str(application)
            assert actual[str(right)]["payment_id"] == str(payment)
            assert actual[str(right)]["policy_version"] == "legacy"
            assert actual[str(right)]["reusable"] is False
