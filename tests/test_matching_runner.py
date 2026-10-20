"""Work #6 Task ①-b: the automatic matching runner on real PostgreSQL.

The runner's seat count is compared against the independent oracle
(`tests/oracle/hard_constraints.py`) on the same small inputs, as the approved contract
requires; the oracle is not imported by the runner itself.
"""

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from oracle.hard_constraints import Participant as OracleParticipant
from oracle.hard_constraints import Table as OracleTable
from oracle.hard_constraints import max_seatable, validate_assignment
from serentable.database import database_engine
from serentable.main import app
from serentable.matching import Participant, plan_allocation, run_due_matches, run_slot_matching
from sqlalchemy import text
from support import SEOUL, login, send, truncate
from test_applications import COMPLETE_PROFILE, apply, hold_lock
from test_payments import pay

SLOT_KEY = ("2026-11-07", "seongsu")
DECISIONS = [
    {"purpose": purpose, "version": "demo-2026-10-16", "accepted": True}
    for purpose in ("privacy", "operation")
]


@pytest.fixture(autouse=True)
def matching_database(seeded_database):
    # Cascades through applications to payments, entitlements and matching rows.
    truncate("event_slot, participant_profile, consent_record")


def due_slot(operator, region="hongdae", days=7, close_in=3.0, capacity=24):
    """A slot closing seconds from now; matching time is just after it.

    The close is real rather than backdated, so "paid by the close" is judged on a genuine
    boundary: the applications below are submitted and paid while it is still open.
    """
    starts = (datetime.now(SEOUL) + timedelta(days=days)).replace(
        hour=19, minute=0, second=0, microsecond=0
    )
    # Deadlines are decided by PostgreSQL; do not assume the host/Docker clocks agree.
    with database_engine().connect() as connection:
        now = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
    closes = now + timedelta(seconds=close_in)
    response = send(
        operator,
        "POST",
        "/api/admin/event-slots",
        {
            "region_code": region,
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "closes_at": closes.isoformat(),
            "matches_at": (closes + timedelta(seconds=0.5)).isoformat(),
            "capacity": capacity,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["event_slot"]["id"]


def prepare(participant, login_id, birth_year=1995):
    """A participant who can be matched: complete profile, both consents."""
    login(participant, login_id)
    saved = send(
        participant, "PUT", "/api/me/profile", {**COMPLETE_PROFILE, "birth_year": birth_year}
    )
    assert saved.status_code == 200, saved.text
    consents = send(participant, "PUT", "/api/me/consents", {"consents": DECISIONS})
    assert consents.json()["complete"] is True


def apply_and_pay(participant, slot_id, paid=True):
    created = apply(participant, [slot_id])
    assert created.status_code == 201, created.text
    application_id = created.json()["application"]["id"]
    if paid:
        response = pay(participant, application_id, "single")
        assert response.status_code == 201, response.text
    return application_id


def stored_states():
    """application id (as text) -> stored matching-axis state."""
    with database_engine().connect() as connection:
        return {
            str(application_id): state
            for application_id, state in connection.execute(
                text("SELECT application_id, state FROM match_participation")
            ).all()
        }


def test_a_participant_is_never_confirmed_at_two_tables_at_the_same_time():
    """PRD §7.4: separate applications for two simultaneous slots seat the user once."""
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, start=1):
            prepare(participant, f"participant-0{index}")
        # Same evening, two regions: the duplicate-candidate rule does not cover this.
        first = due_slot(operator, region="hongdae", close_in=6.0)
        second = due_slot(operator, region="gangnam", close_in=6.0)
        later = [apply_and_pay(participant, second) for participant in members]
        earlier = [apply_and_pay(participant, first) for participant in members]
        time.sleep(6.6)
        summaries = run_due_matches()
        assert sorted(summary["seated_count"] for summary in summaries) == [0, 4]
        states = stored_states()
        confirmed = [a for a in earlier + later if states.get(a) == "CONFIRMED"]
        assert len(confirmed) == 4
        # Already seated at that time: this application's matching ends, with no
        # alternatives offered (it is not a failure to resolve).
        ended = [a for a in earlier + later if states.get(a) == "NO_MATCH"]
        assert len(ended) == 4
        reasons = {item["reason_code"] for s in summaries for item in s["unseated"]}
        assert reasons == {"overlapping_confirmation"}
        for participant, application_id in zip(members, later, strict=True):
            path = f"/api/me/applications/{application_id}/alternatives"
            if application_id in ended:
                assert participant.get(path).status_code == 409
        for participant in members:
            mine = participant.get("/api/me/applications").json()["applications"]
            assert sum(a["matching"]["state"] == "CONFIRMED" for a in mine) == 1


def test_the_run_records_policy_and_table_scores_for_the_operator_only():
    """ADR-0011 / MAT-12: the operator history explains scores; participants never see them."""
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, start=1):
            prepare(participant, f"participant-0{index}")
        slot_id = due_slot(operator)
        for participant in members:
            apply_and_pay(participant, slot_id)
        time.sleep(3.6)
        (summary,) = run_due_matches()
        assert summary["seated_count"] == 4
        (run,) = operator.get("/api/admin/match-runs").json()["match_runs"]
        assert (run["algorithm_version"], run["rule_version"]) == (
            "dp-repair-swap-v1",
            "adr-0011-2026-10-17",
        )
        assert run["policy"]["version"] == "prd-weighted-v1"
        assert run["policy"]["min_score"] == "60"
        (table,) = run["tables"]
        # Same profile for all four (COMPLETE_PROFILE): age 100, interest 100, trait
        # "different" from an identical self trait 0, new 100; gender and MBTI cannot be
        # computed. (.25*100 + .15*100 + .10*0 + .15*100) / .65 = 1100/13 = 84.62.
        assert table["member_count"] == 4
        assert table["score"] == "84.62"
        assert table["components"]["gender"] is None
        assert table["components"]["trait"] == "0.00"
        assert table["explanation"] == {
            "version": 1,
            "birth_year_min": 1995,
            "birth_year_max": 1995,
            "gender_counts": {},
            "gender_unknown_count": 4,
            "mbti_counts": {},
            "mbti_unknown_count": 4,
            "shared_interests": [{"code": "reading", "count": 4}],
            "previous_pair_count": 0,
            "newness_penalized_pair_count": 0,
        }
        for member in run["members"]:
            assert member["explanation"] == {
                "version": 1,
                "trait_satisfaction": {"different": "0.00"},
                "previous_peer_count": 0,
                "transfer_count": 0,
            }
        assert (
            send(
                members[0],
                "PUT",
                "/api/me/profile",
                {**COMPLETE_PROFILE, "birth_year": 1990, "interests": ["music"]},
            ).status_code
            == 200
        )
        history = operator.get("/api/admin/match-runs").json()["match_runs"][0]
        assert history["tables"] == run["tables"]
        assert history["members"] == run["members"]
        assert run_slot_matching(slot_id) is None
        assert (
            operator.get("/api/admin/match-runs").json()["match_runs"][0]["tables"] == run["tables"]
        )
        with database_engine().begin() as connection:
            connection.execute(text("UPDATE dining_table SET explanation=NULL"))
            connection.execute(text("UPDATE match_run_member SET explanation=NULL"))
        legacy = operator.get("/api/admin/match-runs").json()["match_runs"][0]
        assert legacy["tables"][0]["explanation"] is None
        assert all(member["explanation"] is None for member in legacy["members"])
        assert members[0].get("/api/admin/match-runs").status_code == 403
        for participant in members:
            body = participant.get("/api/me/applications").text
            assert "score" not in body and "components" not in body
            assert "explanation" not in body


def test_the_planner_seats_as_many_as_the_oracle_and_never_breaks_a_hard_constraint():
    cases = [
        [1995, 1995, 1995, 1995],
        [1995, 1995, 1995],
        [1980, 1995, 1996, 1997],
        [1995, 1996, 1997, 1998, 1999, 2000, 2001],
        [1975, 1976, 1977, 1978, 1999, 2000, 2001, 2002],
        [1990] * 12,
        [1990, 1990, 1990, 1990, 2001, 2001, 2001, 2001, 2001],
    ]
    for years in cases:
        participants = [
            Participant(application_id=f"a{index}", birth_year=year)
            for index, year in enumerate(years)
        ]
        plan = plan_allocation(participants, capacity=24)
        oracle_roster = [
            OracleParticipant(
                id=f"a{index}", paid=True, consented_slots=frozenset({SLOT_KEY}), birth_year=year
            )
            for index, year in enumerate(years)
        ]
        tables = [
            OracleTable(table_id=f"t{index}", slot=SLOT_KEY, members=members)
            for index, members in enumerate(plan.tables, 1)
        ]
        assert validate_assignment(oracle_roster, tables) == [], years
        # Same meaning as the oracle's count: no score is involved in either.
        assert plan.seated_count == max_seatable(oracle_roster).seated_count, years
        assert plan.seated_count + len(plan.unseated) == len(years)
        # The same input always produces the same tables (deterministic tie-break).
        assert plan_allocation(participants, capacity=24).tables == plan.tables


def test_the_planner_keeps_the_tables_within_the_slot_capacity():
    participants = [Participant(application_id=f"a{index}", birth_year=1995) for index in range(8)]
    plan = plan_allocation(participants, capacity=6)
    assert plan.seated_count == 6
    # Without the limit all eight would sit (4 + 4), so the full slot is the reason.
    assert [reason for _, reason in plan.unseated] == ["capacity", "capacity"]


@pytest.mark.parametrize("capacity, expected", [(24, 13), (8, 8)])
def test_thirteen_compatible_people_are_not_lost_to_greedy_table_sizes(capacity, expected):
    participants = [Participant(application_id=f"a{i}", birth_year=1995) for i in range(13)]
    plan = plan_allocation(participants, capacity)
    assert plan.seated_count == expected
    assert {member for table in plan.tables for member in table} == {
        f"a{i}" for i in range(expected)
    }
    assert all(4 <= len(table) <= 6 for table in plan.tables)


def test_matching_does_not_run_before_the_matching_time():
    with TestClient(app) as operator:
        login(operator, "operator")
        slot_id = due_slot(operator, close_in=120)
        assert run_slot_matching(slot_id) is None
        assert run_due_matches() == []
        with database_engine().connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM match_run")).scalar() == 0


def test_four_paid_applications_are_seated_at_one_table_and_reported_over_http():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, start=1):
            prepare(participant, f"participant-0{index}")
        slot_id = due_slot(operator)
        applications = [apply_and_pay(participant, slot_id) for participant in members]
        time.sleep(3.6)
        (summary,) = run_due_matches()
        assert (summary["state"], summary["seated_count"]) == ("SUCCEEDED", 4)
        assert [len(table) for table in summary["tables"]] == [4]
        assert summary["unseated"] == []

        # Participant view: the stored matching axis, not a derived guess.
        listed = members[0].get("/api/me/applications").json()["applications"]
        assert listed[0]["matching"]["state"] == "CONFIRMED"
        assert listed[0]["matching"]["reason_code"] is None
        assert listed[0]["matching"]["event_slot_id"] == slot_id
        assert listed[0]["matching"]["table"]["member_count"] == 4
        # The approved minimal introduction must not include contact/Instagram/name.
        assert (
            listed[0]["matching"]["table"]["members"]
            == [{"display_name": COMPLETE_PROFILE["display_name"]}] * 4
        )

        # Operator view: one read-only run generation with its members and reasons.
        history = operator.get("/api/admin/match-runs")
        assert history.status_code == 200
        assert history.headers["cache-control"] == "no-store"
        (run,) = history.json()["match_runs"]
        assert (run["state"], run["attempt"], run["seated_count"]) == ("SUCCEEDED", 1, 4)
        assert run["rule_version"] and run["algorithm_version"]
        assert sorted(member["outcome"] for member in run["members"]) == ["SEATED"] * 4
        assert sorted(member["login_id"] for member in run["members"]) == [
            f"participant-0{index}" for index in range(1, 5)
        ]
        # The route is operator-only.
        assert members[0].get("/api/admin/match-runs").status_code == 403
        with database_engine().connect() as connection:
            assert (
                connection.execute(
                    text("""SELECT count(*) FROM table_assignment
                    WHERE ended_at IS NULL AND event_slot_id = :slot"""),
                    {"slot": slot_id},
                ).scalar()
                == 4
            )
        assert stored_states() == {application_id: "CONFIRMED" for application_id in applications}


def test_confirmation_uses_the_single_pass_once_and_retries_keep_its_usage_time():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, 1):
            prepare(participant, f"participant-0{index}")
        slot = due_slot(operator)
        for participant in members:
            apply_and_pay(participant, slot)
        before = members[0].get("/api/me/entitlements").json()["entitlements"]
        assert len(before) == 1 and before[0]["state"] == "HELD"
        time.sleep(3.6)
        assert run_slot_matching(slot)["state"] == "SUCCEEDED"
        used = members[0].get("/api/me/entitlements").json()["entitlements"]
        assert len(used) == 1
        assert used[0]["state"] == "USED"
        assert datetime.fromisoformat(used[0]["used_at"]) >= datetime.fromisoformat(
            used[0]["starts_at"]
        )
        application = members[0].get("/api/me/applications").json()["applications"][0]
        assert application["coverage"]["entitlement"] == used[0]
        assert application["matching"]["state"] == "CONFIRMED"
        assert run_slot_matching(slot) is None
        assert members[0].get("/api/me/entitlements").json()["entitlements"] == used


def test_unpaid_and_too_few_applications_are_left_out_with_a_reason():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, start=1):
            prepare(participant, f"participant-0{index}")
        slot_id = due_slot(operator)
        paid = [apply_and_pay(participant, slot_id) for participant in members[:3]]
        unpaid = apply_and_pay(members[3], slot_id, paid=False)
        time.sleep(3.6)
        (summary,) = run_due_matches()
        # The unpaid application is not a target at all; three are not enough for a table.
        assert (summary["state"], summary["seated_count"]) == ("SUCCEEDED", 0)
        assert {item["reason_code"] for item in summary["unseated"]} == {"not_enough_eligible"}
        assert stored_states() == {application_id: "ALTERNATIVE_OFFERED" for application_id in paid}
        # No run reached the unpaid application, so its stored axis stays empty.
        assert unpaid not in stored_states()
        listed = members[3].get("/api/me/applications").json()["applications"]
        assert listed[0]["matching"] is None
        for participant in members[:3]:
            (held,) = participant.get("/api/me/entitlements").json()["entitlements"]
            assert held["state"] == "HELD" and held["used_at"] is None


def test_a_database_failure_rolls_back_all_confirmations_and_rights_before_retry():
    """Fail at the DB commit boundary after assignments, rather than mocking the engine."""
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, 1):
            prepare(participant, f"participant-0{index}")
        slot = due_slot(operator)
        for participant in members:
            apply_and_pay(participant, slot)
        time.sleep(3.6)
        with database_engine().begin() as connection:
            connection.execute(text("CREATE SEQUENCE test_confirmation_failure"))
            connection.execute(
                text("""CREATE FUNCTION test_confirmation_failure() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
                IF NEW.state = 'SUCCEEDED' AND nextval('test_confirmation_failure') = 1 THEN
                    RAISE EXCEPTION 'synthetic confirmation failure';
                END IF; RETURN NEW;
            END $$""")
            )
            connection.execute(
                text("""CREATE TRIGGER test_confirmation_failure
            BEFORE UPDATE ON match_run FOR EACH ROW
            EXECUTE FUNCTION test_confirmation_failure()""")
            )
        try:
            assert run_slot_matching(slot)["state"] == "FAILED"
            failures = operator.get("/api/admin/exceptions").json()["exceptions"]
            failure = [item for item in failures if item["event_slot_id"] == slot]
            assert len(failure) == 1
            assert failure[0]["kind"] == "matching_failure"
            assert failure[0]["resolvable"] is False
            assert (
                operator.get("/api/admin/exceptions", params={"state": "RESOLVED"}).json()[
                    "exceptions"
                ]
                == []
            )
            assert (
                send(
                    operator,
                    "POST",
                    f"/api/admin/exceptions/matching_failure/{failure[0]['id']}/resolve",
                    {"note": "재시도 대기"},
                ).status_code
                == 409
            )
            summary = operator.get("/api/admin/dashboard", params={"event_slot_id": slot}).json()[
                "slots"
            ][0]
            assert summary["open_exception_count"] == 1
            assert members[0].get("/api/admin/exceptions").status_code == 403
            for participant in members:
                (application,) = participant.get("/api/me/applications").json()["applications"]
                assert application["matching"]["state"] == "EXCEPTION"
                assert application["matching"]["table"] is None
                (held,) = participant.get("/api/me/entitlements").json()["entitlements"]
                assert held["state"] == "HELD" and held["used_at"] is None
            recovered = run_slot_matching(slot)
            assert (recovered["state"], recovered["attempt"], recovered["seated_count"]) == (
                "SUCCEEDED",
                2,
                4,
            )
            for participant in members:
                (application,) = participant.get("/api/me/applications").json()["applications"]
                assert application["matching"]["state"] == "CONFIRMED"
                assert application["matching"]["table"]["member_count"] == 4
                (used,) = participant.get("/api/me/entitlements").json()["entitlements"]
                assert used["state"] == "USED" and used["used_at"] is not None
            runs = operator.get("/api/admin/match-runs").json()["match_runs"]
            assert [run["state"] for run in runs] == ["SUCCEEDED", "FAILED"]
            assert [run["seated_count"] for run in runs] == [4, 0]
            assert operator.get("/api/admin/exceptions").json()["exceptions"] == []
            summary = operator.get("/api/admin/dashboard", params={"event_slot_id": slot}).json()[
                "slots"
            ][0]
            assert summary["open_exception_count"] == 0
        finally:
            with database_engine().begin() as connection:
                connection.execute(text("DROP TRIGGER test_confirmation_failure ON match_run"))
                connection.execute(text("DROP FUNCTION test_confirmation_failure()"))
                connection.execute(text("DROP SEQUENCE test_confirmation_failure"))


def test_membership_remains_active_after_confirmation_and_does_not_become_single_use():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, 1):
            prepare(participant, f"participant-0{index}")
        slot = due_slot(operator)
        for participant in members:
            application_id = apply(participant, [slot]).json()["application"]["id"]
            assert pay(participant, application_id, "membership_1m").status_code == 201
        time.sleep(3.6)
        assert run_slot_matching(slot)["seated_count"] == 4
        (membership,) = members[0].get("/api/me/entitlements").json()["entitlements"]
        assert membership["state"] == "ACTIVE" and membership["used_at"] is None


def test_an_age_gap_leaves_the_table_unbuilt_and_names_the_reason():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, birth_year in enumerate([1980, 1994, 1995, 1996], start=1):
            prepare(members[index - 1], f"participant-0{index}", birth_year=birth_year)
        slot_id = due_slot(operator)
        applications = [apply_and_pay(participant, slot_id) for participant in members]
        time.sleep(3.6)
        (summary,) = run_due_matches()
        assert summary["seated_count"] == 0
        reasons = {item["application_id"]: item["reason_code"] for item in summary["unseated"]}
        assert reasons[applications[0]] == "age_gap"
        assert set(reasons.values()) <= {"age_gap", "no_valid_table"}
        assert set(stored_states().values()) == {"ALTERNATIVE_OFFERED"}


def test_a_multi_slot_application_is_seated_in_only_its_earliest_slot():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, start=1):
            prepare(participant, f"participant-0{index}")
        first = due_slot(operator, region="hongdae", close_in=6.0)
        second = due_slot(operator, region="gangnam", days=8, close_in=6.0)
        applications = []
        for participant in members:
            created = apply(participant, [first, second])
            assert created.status_code == 201, created.text
            application_id = created.json()["application"]["id"]
            assert pay(participant, application_id, "single").status_code == 201
            applications.append(application_id)
        time.sleep(6.6)
        summaries = run_due_matches()
        # The earlier slot takes them; the later one finds nothing left to seat (U07).
        assert sorted(summary["seated_count"] for summary in summaries) == [0, 4]
        assert all(summary["state"] == "SUCCEEDED" for summary in summaries)
        assert stored_states() == {application_id: "CONFIRMED" for application_id in applications}
        with database_engine().connect() as connection:
            live, distinct = connection.execute(
                text("""SELECT count(*), count(DISTINCT application_id) FROM table_assignment
                WHERE ended_at IS NULL""")
            ).one()
            assert (live, distinct) == (4, 4)
            assert set(
                connection.execute(
                    text("SELECT DISTINCT event_slot_id FROM table_assignment")
                ).scalars()
            ) == {uuid.UUID(first)}


def test_a_slot_runs_once_and_a_repeated_cycle_does_not_run_it_again():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, start=1):
            prepare(participant, f"participant-0{index}")
        slot_id = due_slot(operator)
        applications = [apply_and_pay(participant, slot_id) for participant in members]
        time.sleep(3.6)
        assert len(run_due_matches()) == 1
        assert run_due_matches() == []
        assert run_slot_matching(slot_id) is None
        with database_engine().connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM match_run")).scalar() == 1
            assert connection.execute(text("SELECT count(*) FROM table_assignment")).scalar() == 4
            assert (
                connection.execute(
                    text("SELECT count(*) FROM dining_table WHERE event_slot_id = :slot"),
                    {"slot": slot_id},
                ).scalar()
                == 1
            )
        assert stored_states() == {application_id: "CONFIRMED" for application_id in applications}


def test_an_interrupted_generation_is_abandoned_and_replaced_by_a_new_attempt():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, start=1):
            prepare(participant, f"participant-0{index}")
        slot_id = due_slot(operator)
        for participant in members:
            apply_and_pay(participant, slot_id)
        time.sleep(3.6)
        # A durable stale RUNNING fixture exercises legacy/manual recovery. An actual
        # killed worker rolls back its uncommitted generation; test_worker_crash_recovery
        # checks that different case through a separate process and the public API.
        with database_engine().begin() as connection:
            connection.execute(
                text("""INSERT INTO match_run
                (id, event_slot_id, attempt, state, algorithm_version, rule_version,
                 seated_count, started_at)
                VALUES (:id, :slot, 1, 'RUNNING', 'interrupted', 'interrupted', 0, now())"""),
                {"id": uuid.uuid4(), "slot": slot_id},
            )
        summary = run_slot_matching(slot_id)
        assert (summary["state"], summary["attempt"], summary["seated_count"]) == (
            "SUCCEEDED",
            2,
            4,
        )
        with database_engine().connect() as connection:
            generations = connection.execute(
                text("""SELECT attempt, state, reason_code FROM match_run
                WHERE event_slot_id = :slot ORDER BY attempt"""),
                {"slot": slot_id},
            ).all()
            assert [(attempt, state) for attempt, state, _ in generations] == [
                (1, "ABANDONED"),
                (2, "SUCCEEDED"),
            ]
            assert generations[0][2] == "stale_generation"
            # The abandoned generation left no table behind.
            assert (
                connection.execute(
                    text("SELECT count(*) FROM table_assignment WHERE event_slot_id = :slot"),
                    {"slot": slot_id},
                ).scalar()
                == 4
            )


def test_only_one_concurrent_runner_seats_a_slot():
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, start=1):
            prepare(participant, f"participant-0{index}")
        slot_id = due_slot(operator)
        for participant in members:
            apply_and_pay(participant, slot_id)
        time.sleep(3.6)
        connection, transaction = hold_lock(
            "SELECT id FROM event_slot WHERE id = :id FOR UPDATE", {"id": slot_id}
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(run_slot_matching, slot_id) for _ in range(2)]
            time.sleep(1)
            transaction.rollback()
            connection.close()
            results = [future.result(timeout=20) for future in pending]
        assert [result is not None for result in results].count(True) == 1
        with database_engine().connect() as after:
            assert after.execute(text("SELECT count(*) FROM match_run")).scalar() == 1
            assert after.execute(text("SELECT count(*) FROM table_assignment")).scalar() == 4
        assert set(stored_states().values()) == {"CONFIRMED"}


def test_late_failure_record_cannot_replace_a_successful_retry():
    """A genuine database failure pauses at the log boundary, after rollback."""
    failed, resume = threading.Event(), threading.Event()

    class PauseFailure(logging.Handler):
        def emit(self, record):
            if record.getMessage() == "matching_run_failed":
                failed.set()
                assert resume.wait(15)

    handler = PauseFailure()
    worker_logger = logging.getLogger("serentable.worker")
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(3)]
        login(operator, "operator")
        for index, participant in enumerate(members, 1):
            prepare(participant, f"participant-0{index}")
        slot = due_slot(operator)
        for participant in members:
            apply_and_pay(participant, slot)
        time.sleep(3.6)
        # A PostgreSQL sequence survives rollback: only the first RUNNING insert fails.
        with database_engine().begin() as connection:
            connection.execute(text("CREATE SEQUENCE test_matching_failure"))
            connection.execute(
                text("""CREATE FUNCTION test_matching_failure() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN
                IF NEW.state = 'RUNNING' AND nextval('test_matching_failure') = 1 THEN
                    RAISE EXCEPTION 'synthetic database failure';
                END IF; RETURN NEW; END $$""")
            )
            connection.execute(
                text("""CREATE TRIGGER test_matching_failure
                BEFORE INSERT ON match_run FOR EACH ROW
                EXECUTE FUNCTION test_matching_failure()""")
            )
        worker_logger.addHandler(handler)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(run_slot_matching, slot)
                try:
                    assert failed.wait(10)
                    successful = run_slot_matching(slot)
                    assert successful["state"] == "SUCCEEDED"
                finally:
                    resume.set()
                pending.result(timeout=10)
        finally:
            resume.set()
            worker_logger.removeHandler(handler)
            with database_engine().begin() as connection:
                connection.execute(text("DROP TRIGGER test_matching_failure ON match_run"))
                connection.execute(text("DROP FUNCTION test_matching_failure()"))
                connection.execute(text("DROP SEQUENCE test_matching_failure"))
        runs = operator.get("/api/admin/match-runs").json()["match_runs"]
        assert [run["state"] for run in runs] == ["SUCCEEDED"]
        for participant in members:
            application = participant.get("/api/me/applications").json()["applications"][0]
            assert application["matching"]["state"] == "ALTERNATIVE_OFFERED"


def test_cancel_and_matching_do_not_deadlock_on_the_assignment_foreign_key(monkeypatch):
    import serentable.applications as applications_api

    paused, resume = threading.Event(), threading.Event()
    actual_clock = applications_api.locked_now
    first = True

    def pause_after_application_lock(connection):
        nonlocal first
        moment = actual_clock(connection)
        if first:
            first = False
            paused.set()
            assert resume.wait(15)
        return moment

    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, participant in enumerate(members, 1):
            prepare(participant, f"participant-0{index}")
        slot = due_slot(operator)
        application_ids = [apply_and_pay(participant, slot) for participant in members]
        # Only time acquisition is paused; requests, FK checks and locks are real.
        monkeypatch.setattr(applications_api, "locked_now", pause_after_application_lock)
        with ThreadPoolExecutor(max_workers=2) as pool:
            canceled = pool.submit(
                send, members[0], "POST", f"/api/me/applications/{application_ids[0]}/cancel"
            )
            try:
                assert paused.wait(5)
                time.sleep(3.6)
                matching = pool.submit(run_slot_matching, slot)
                time.sleep(0.3)
            finally:
                resume.set()
            result = canceled.result(timeout=10)
            summary = matching.result(timeout=10)
        assert result.status_code == 409
        assert summary["state"] == "SUCCEEDED"
        assert summary["seated_count"] == 4
        runs = operator.get("/api/admin/match-runs").json()["match_runs"]
        assert [run["state"] for run in runs] == ["SUCCEEDED"]
