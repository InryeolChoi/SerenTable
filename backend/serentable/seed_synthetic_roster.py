"""Explicit local demo provisioning; never reads or transforms source responses."""

import argparse
import json
import os
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from serentable.auth import password_hasher
from serentable.profile import Profile

RULES_VERSION = "independent-synthetic-roster-v1"
COUNT = 100
LOGIN_PREFIX = "synthetic-demo-"
INTERESTS = (
    "movies_drama",
    "music",
    "reading",
    "writing",
    "exercise",
    "food_cafes",
    "travel",
    "photo_video",
    "exhibitions_performances_art",
    "fashion_beauty",
    "self_development_study",
)
MBTIS = (
    "ISTJ",
    "ISFJ",
    "INFJ",
    "INTJ",
    "ISTP",
    "ISFP",
    "INFP",
    "INTP",
    "ESTP",
    "ESFP",
    "ENFP",
    "ENTP",
    "ESTJ",
    "ESFJ",
    "ENFJ",
    "ENTJ",
)


class SeedConflict(Exception):
    pass


def profile_for(index):
    """All initial fields are invented, labelled synthetic, and independent of data/."""
    return Profile(
        name=f"합성 데모 참가자 {index:03d}",
        display_name=f"합성 참가자 {index:03d}",
        contact=f"DEMO-NOT-A-PHONE-{index:03d}",
        instagram_id=f"synthetic_demo_{index:03d}",
        birth_year=1990 + (index - 1) % 16,
        gender="여성" if index % 2 else "남성",
        occupation="합성 데모 직업",
        mbtis=[MBTIS[(index - 1) % len(MBTIS)]],
        interests=[INTERESTS[(index - 1 + offset) % len(INTERESTS)] for offset in range(3)],
        self_traits=["listener" if index % 2 else "conversation_leader"],
        desired_traits=["similar"],
        meal_budget_bands=["10000_20000", "20000_30000"],
    )


def configuration():
    if os.getenv("SYNTHETIC_DEMO_SEED_ENABLED") != "1" or os.getenv("APP_ENV") == "production":
        raise ValueError
    password = os.getenv("DEMO_PARTICIPANT_PASSWORD", "")
    if not 12 <= len(password) <= 128:
        raise ValueError
    url = make_url(os.environ["DATABASE_URL"])
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not (url.database or "").startswith("serentable_demo_")
        or url.query
        or any(
            os.getenv(key)
            for key in (
                "PGHOST",
                "PGHOSTADDR",
                "PGPORT",
                "PGDATABASE",
                "PGSERVICE",
                "PGSERVICEFILE",
                "PGOPTIONS",
            )
        )
    ):
        raise ValueError
    return url.set(drivername="postgresql+psycopg", port=url.port or 5432), password


def load(url, password):
    hashed = password_hasher.hash(password)
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    counts = {"created_accounts": 0, "created_profiles": 0}
    try:
        with engine.begin() as connection:
            # Serialize this seed only; profile edits keep the normal row-level locks.
            connection.execute(text("SELECT pg_advisory_xact_lock(710171100)"))
            for index in range(1, COUNT + 1):
                login_id = f"{LOGIN_PREFIX}{index:03d}"
                user_id = uuid.uuid5(uuid.NAMESPACE_URL, f"serentable:synthetic-demo:v1:{login_id}")
                created = connection.execute(
                    text("""INSERT INTO app_user(id, login_id, password_hash, role, active)
                    VALUES (:id, :login, :hash, 'participant', true)
                    ON CONFLICT (login_id) DO NOTHING RETURNING id"""),
                    {"id": user_id, "login": login_id, "hash": hashed},
                ).scalar()
                existing = connection.execute(
                    text("SELECT id, role FROM app_user WHERE login_id = :login FOR UPDATE"),
                    {"login": login_id},
                ).one()
                if existing.id != user_id or existing.role != "participant":
                    raise SeedConflict
                counts["created_accounts"] += int(created is not None)
                saved = connection.execute(
                    text("""INSERT INTO participant_profile(user_id, data)
                    VALUES (:id, CAST(:data AS jsonb))
                    ON CONFLICT (user_id) DO NOTHING RETURNING user_id"""),
                    {"id": user_id, "data": profile_for(index).model_dump_json()},
                ).scalar()
                counts["created_profiles"] += int(saved is not None)
    finally:
        engine.dispose()
    return {**preview(), **counts}


def preview():
    return {
        "rules_version": RULES_VERSION,
        "participant_count": COUNT,
        "source_linked": False,
        "login_prefix": LOGIN_PREFIX,
        "birth_year_range": [1990, 2005],
        "creates_consents": False,
        "creates_payments": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "load"))
    args = parser.parse_args()
    if args.command == "preview":
        print(json.dumps(preview(), ensure_ascii=False))
        return 0
    try:
        url, password = configuration()
    except (ValueError, KeyError, SQLAlchemyError):
        print("synthetic_roster_configuration_invalid", file=sys.stderr)
        return 2
    try:
        result = load(url, password)
    except SeedConflict:
        print("synthetic_roster_identity_conflict", file=sys.stderr)
        return 1
    except (SQLAlchemyError, ValueError):
        print("synthetic_roster_unavailable", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
