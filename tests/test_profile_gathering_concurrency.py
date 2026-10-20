"""Profile saves and gathering notifications both complete on real PostgreSQL."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

from fastapi.testclient import TestClient
from serentable.database import database_engine
from serentable.gatherings import run_gathering_jobs
from serentable.main import app
from serentable.matching import run_due_matches
from sqlalchemy import event
from support import login, send, truncate
from test_applications import COMPLETE_PROFILE
from test_matching_runner import apply_and_pay, due_slot, prepare


def test_profile_save_and_first_gathering_notifications_do_not_deadlock(seeded_database):
    truncate("event_slot, participant_profile, consent_record")
    with ExitStack() as stack:
        operator = stack.enter_context(TestClient(app))
        members = [stack.enter_context(TestClient(app)) for _ in range(4)]
        login(operator, "operator")
        for index, member in enumerate(members, 1):
            prepare(member, f"participant-0{index}")
        slot = due_slot(operator, close_in=6)
        for member in members:
            apply_and_pay(member, slot)
        time.sleep(6.6)
        assert run_due_matches()[0]["seated_count"] == 4
        shared = threading.Event()
        user_locked = threading.Event()
        engine = database_engine()

        # Scheduling barriers only: both transactions execute their real SQL and commit.
        def after_sql(connection, cursor, statement, params, context, many):
            if "FOR SHARE OF p" in statement and threading.current_thread().name == "gathering":
                shared.set()
                assert user_locked.wait(10), "profile never acquired the user lock"
            if "SELECT id FROM app_user WHERE id=" in statement and shared.is_set():
                user_locked.set()

        def gathering():
            threading.current_thread().name = "gathering"
            run_gathering_jobs()

        event.listen(engine, "after_cursor_execute", after_sql)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(gathering)
                assert shared.wait(10), "gathering never acquired profile locks"
                saved = send(
                    members[0],
                    "PUT",
                    "/api/me/profile",
                    {**COMPLETE_PROFILE, "occupation": "합성 변경 직업"},
                )
                future.result(timeout=15)
        finally:
            event.remove(engine, "after_cursor_execute", after_sql)
        assert saved.status_code == 200, saved.text
        profile = members[0].get("/api/me/profile").json()
        assert profile["profile"]["occupation"] == "합성 변경 직업"
        notices = members[0].get("/api/me/notifications").json()["notifications"]
        assert sum(n["kind"] == "CONFIRMED" for n in notices) == 1
