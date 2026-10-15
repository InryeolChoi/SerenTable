"""Foundation heartbeat only; no matching/notification jobs are implemented yet."""

import argparse
import logging
import signal
import threading

from sqlalchemy import text

from serentable.database import database_engine

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
        stop.wait(10)


if __name__ == "__main__":
    main()
