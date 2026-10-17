"""Work #8 T2: private feedback, per-person preferences and the single reminder (FDB-02~04)."""

import time
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.main import app
from sqlalchemy import text
from support import login, send, truncate

RATINGS = {
    "table_rating": 5,
    "conversation_rating": 4,
    "venue_rating": 3,
    "rejoin_intent": 5,
    "recommend_intent": 4,
}


@pytest.fixture
def table(seeded_database):
    """A real confirmed four-person table (participant-01..04) from the matching runner."""
    from serentable.matching import run_due_matches
    from test_matching_runner import apply_and_pay, due_slot, prepare

    truncate(
        "event_slot, participant_profile, consent_record, app_notification, participant_exclusion"
    )
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for i, member in enumerate(members, 1):
            prepare(member, f"participant-0{i}")
        slot = due_slot(operator, close_in=4)
        for member in members:
            apply_and_pay(member, slot)
        time.sleep(4.6)
        assert run_due_matches()[0]["seated_count"] == 4
        table_id = members[0].get("/api/me/gatherings").json()["gatherings"][0]["id"]
        ids = [member.get("/api/auth/me").json()["user"]["id"] for member in members]
        yield {
            "operator": operator,
            "members": members,
            "ids": ids,
            "slot": slot,
            "id": table_id,
        }


def end_slot(slot, ended_ago="1 hour"):
    """Fixture clock: move only this isolated slot into the past."""
    with database_engine().begin() as connection:
        connection.execute(
            text(f"""UPDATE event_slot SET ends_at=now()-interval '{ended_ago}',
            starts_at=now()-interval '{ended_ago}'-interval '2 hours',
            matches_at=now()-interval '{ended_ago}'-interval '1 day',
            closes_at=now()-interval '{ended_ago}'-interval '1 day 1 minute'
            WHERE id=:slot"""),
            {"slot": slot},
        )


def path(table_id, kind="feedback"):
    return f"/api/me/tables/{table_id}/{kind}"


def test_feedback_opens_only_after_the_end_and_can_be_revised(table):
    member = table["members"][0]
    early = send(member, "PUT", path(table["id"]), RATINGS)
    assert early.status_code == 409
    assert early.json()["detail"] == "feedback_not_open"
    assert member.get(path(table["id"])).json()["feedback"] is None

    end_slot(table["slot"])
    saved = send(member, "PUT", path(table["id"]), RATINGS)
    assert saved.status_code == 200, saved.text
    assert saved.json()["feedback"] == RATINGS
    again = send(member, "PUT", path(table["id"]), RATINGS)
    assert again.json() == saved.json()
    revised = send(member, "PUT", path(table["id"]), {**RATINGS, "venue_rating": 1})
    assert revised.json()["feedback"]["venue_rating"] == 1
    assert member.get(path(table["id"])).json()["feedback"]["venue_rating"] == 1
    assert send(member, "PUT", path(table["id"]), {**RATINGS, "table_rating": 6}).status_code == 422
    assert member.put(path(table["id"]), json=RATINGS).status_code == 403


def exclusions():
    with database_engine().connect() as connection:
        return {
            (str(low), str(high), source)
            for low, high, source in connection.execute(
                text("SELECT user_low,user_high,source FROM participant_exclusion")
            ).all()
        }


def test_only_current_tablemates_can_be_rated_after_the_end(table):
    rater, *_ = table["members"]
    me, mate, _, leaver = table["ids"]
    choice = {"preferences": [{"target_id": mate, "choice": "MEET_AGAIN"}]}
    early = send(rater, "PUT", path(table["id"], "preferences"), choice)
    assert early.status_code == 409
    end_slot(table["slot"])
    # A member whose seat ended is no longer a tablemate and loses access to the table.
    with database_engine().begin() as connection:
        connection.execute(
            text("""UPDATE table_assignment SET ended_at=now()
            WHERE dining_table_id=:table AND user_id=:user"""),
            {"table": table["id"], "user": leaver},
        )
    operator_id = table["operator"].get("/api/auth/me").json()["user"]["id"]
    for target in (me, leaver, operator_id):
        refused = send(
            rater,
            "PUT",
            path(table["id"], "preferences"),
            {"preferences": [{"target_id": target, "choice": "AVOID"}]},
        )
        assert refused.status_code == 422, target
        assert refused.json()["detail"] == "target_not_tablemate"
    assert exclusions() == set()
    assert table["members"][3].get(path(table["id"])).status_code == 404
    assert send(table["members"][3], "PUT", path(table["id"]), RATINGS).status_code == 404
    mates = [m["user_id"] for m in rater.get(path(table["id"])).json()["tablemates"]]
    assert sorted(mates) == sorted(table["ids"][1:3])
    saved = send(rater, "PUT", path(table["id"], "preferences"), choice)
    assert saved.status_code == 200, saved.text
    chosen = {m["user_id"]: m["preference"] for m in saved.json()["tablemates"]}
    assert chosen[mate] == "MEET_AGAIN"
    assert table["operator"].get(path(table["id"])).status_code == 403


def test_avoid_records_the_exclusion_atomically_and_stays_private(table):
    rater, target_client, *_ = table["members"]
    me, target = table["ids"][:2]
    end_slot(table["slot"])
    avoid = {"preferences": [{"target_id": target, "choice": "AVOID"}]}
    # The approved storage-fault seam: the exclusion insert fails inside the request.
    with database_engine().begin() as c:
        c.execute(
            text("""CREATE FUNCTION feedback_test_fail() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$""")
        )
        c.execute(
            text("""CREATE TRIGGER feedback_test_fault BEFORE INSERT ON participant_exclusion
            FOR EACH ROW EXECUTE FUNCTION feedback_test_fail()""")
        )
    try:
        failed = send(rater, "PUT", path(table["id"], "preferences"), avoid)
        assert failed.status_code == 503
    finally:
        with database_engine().begin() as c:
            c.execute(text("DROP TRIGGER feedback_test_fault ON participant_exclusion"))
            c.execute(text("DROP FUNCTION feedback_test_fail()"))
    assert exclusions() == set()
    mates = rater.get(path(table["id"])).json()["tablemates"]
    assert {m["user_id"]: m["preference"] for m in mates}[target] is None

    saved = send(rater, "PUT", path(table["id"], "preferences"), avoid)
    assert saved.status_code == 200, saved.text
    assert send(rater, "PUT", path(table["id"], "preferences"), avoid).json() == saved.json()
    low, high = sorted((me, target))
    assert exclusions() == {(low, high, "avoid")}
    # The target sees only a display name for the rater, never the choice about them.
    seen = target_client.get(path(table["id"]))
    assert {m["user_id"]: m["preference"] for m in seen.json()["tablemates"]}[me] is None
    assert "AVOID" not in seen.text
    assert "AVOID" not in target_client.get("/api/me/notifications").text
    # Clearing the choice keeps the safety exclusion.
    cleared = send(
        rater,
        "PUT",
        path(table["id"], "preferences"),
        {"preferences": [{"target_id": target, "choice": None}]},
    )
    assert {m["user_id"]: m["preference"] for m in cleared.json()["tablemates"]}[target] is None
    assert exclusions() == {(low, high, "avoid")}


def reminders(client):
    return [
        n
        for n in client.get("/api/me/notifications").json()["notifications"]
        if n["kind"] == "FEEDBACK_REMINDER"
    ]


def test_unanswered_members_get_exactly_one_reminder_after_a_day(table):
    from concurrent.futures import ThreadPoolExecutor

    from serentable.feedback import run_feedback_jobs

    answered, *silent = table["members"]
    end_slot(table["slot"], "23 hours")
    assert send(answered, "PUT", path(table["id"]), RATINGS).status_code == 200
    run_feedback_jobs()
    assert all(reminders(member) == [] for member in table["members"])

    end_slot(table["slot"], "25 hours")
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(run_feedback_jobs) for _ in range(2)]:
            future.result()
    run_feedback_jobs()
    assert reminders(answered) == []
    for member in silent:
        sent = reminders(member)
        assert len(sent) == 1
        assert sent[0]["url"] == "/participant/history"
    # Answering later never brings another reminder.
    assert send(silent[0], "PUT", path(table["id"]), RATINGS).status_code == 200
    run_feedback_jobs()
    assert len(reminders(silent[0])) == 1


def test_a_long_past_table_is_not_reminded_retroactively(table):
    from serentable.feedback import run_feedback_jobs

    end_slot(table["slot"], "30 days")
    run_feedback_jobs()
    assert all(reminders(member) == [] for member in table["members"])


def test_unanswered_feedback_never_blocks_a_new_application(table):
    from serentable.feedback import run_feedback_jobs
    from test_applications import apply, create_slot

    end_slot(table["slot"], "25 hours")
    run_feedback_jobs()
    member = table["members"][1]
    assert len(reminders(member)) == 1
    created = apply(member, [create_slot(table["operator"])])
    assert created.status_code == 201, created.text
