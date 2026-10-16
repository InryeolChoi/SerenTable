"""Explicit operator CLI: create synthetic accounts without printing credentials."""

import os
import sys
import uuid

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from serentable.auth import password_hasher
from serentable.database import database_engine


def main() -> int:
    if len(sys.argv) != 1:
        print("seed_demo_accounts_accepts_no_arguments", file=sys.stderr)
        return 2
    participant = os.getenv("DEMO_PARTICIPANT_PASSWORD", "")
    operator = os.getenv("DEMO_OPERATOR_PASSWORD", "")
    if not all(12 <= len(value) <= 128 for value in (participant, operator)):
        print("demo_password_environment_required", file=sys.stderr)
        return 2
    try:
        participant_hash = password_hasher.hash(participant)
        operator_hash = password_hasher.hash(operator)
        accounts = [(f"participant-{i:02d}", "participant", participant_hash) for i in range(1, 5)]
        accounts.append(("operator", "operator", operator_hash))
        with database_engine().begin() as connection:
            for login_id, role, hashed in accounts:
                connection.execute(
                    text("""
                    INSERT INTO app_user(id, login_id, password_hash, role, active)
                    VALUES (:id, :login_id, :hash, :role, true)
                    ON CONFLICT (login_id) DO NOTHING
                """),
                    {"id": uuid.uuid4(), "login_id": login_id, "hash": hashed, "role": role},
                )
    except (SQLAlchemyError, KeyError, ValueError):
        print("demo_seed_unavailable", file=sys.stderr)
        return 1
    print("synthetic_demo_accounts_ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
