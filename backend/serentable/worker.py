"""The separate runner: a heartbeat, and the automatic matching of due slots (MAT-01).

Matching has no public trigger and no operator start; this loop is the only entry point.
Gathering jobs run after matching without rewriting confirmed assignments."""

import argparse
import logging
import signal
import threading
import time

from sqlalchemy import text

from serentable.database import database_engine
from serentable.gatherings import run_gathering_jobs
from serentable.matching import run_due_matches

logger = logging.getLogger("serentable.worker")


def heartbeat():
    with database_engine().begin() as connection:
        connection.execute(
            text("""
            INSERT INTO worker_heartbeat (name, last_seen)
            VALUES ('scheduler', CURRENT_TIMESTAMP)
            ON CONFLICT (name) DO UPDATE SET last_seen = CURRENT_TIMESTAMP
        """)
        )
    logger.info("worker_heartbeat_ok")


def match_due_slots():
    """Match due slots once. Failures are logged; the next cycle retries what it left."""
    started = time.monotonic()
    try:
        summaries = run_due_matches()
    except Exception:
        # Do not log driver exceptions: their strings may contain connection details.
        logger.error("worker_matching_unavailable")
        return
    if summaries:
        logger.info("worker_matching_ok runs=%d", len(summaries))
    logger.info("worker_matching_timed matching_ms=%d", (time.monotonic() - started) * 1000)


def gathering_jobs():
    from serentable.feedback import run_feedback_jobs
    from serentable.notifications import dispatch_notifications

    timings = []
    try:
        for name, job in (
            ("gathering", run_gathering_jobs),
            ("feedback", run_feedback_jobs),
            ("notifications", dispatch_notifications),
        ):
            started = time.monotonic()
            job()
            timings.append(f"{name}_ms={round((time.monotonic() - started) * 1000)}")
    except Exception:
        logger.error("worker_gathering_unavailable")
    # Durations only: a cycle longer than the 30 s heartbeat window reads as a dead worker.
    logger.info("worker_jobs_timed %s", " ".join(timings))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.once:
        try:
            heartbeat()
        except Exception:
            logger.error("worker_database_unavailable")
            raise SystemExit(1) from None
        match_due_slots()
        gathering_jobs()
        return
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        try:
            heartbeat()
        except Exception:
            # Do not log driver exceptions: their strings may contain connection details.
            logger.error("worker_database_unavailable")
        else:
            match_due_slots()
            gathering_jobs()
        stop.wait(10)


if __name__ == "__main__":
    main()
