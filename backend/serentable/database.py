import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


@lru_cache(maxsize=4)
def engine_for(url: str):
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL is required")
    parsed = parsed.set(drivername="postgresql+psycopg")
    return create_engine(parsed, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def database_engine():
    return engine_for(os.environ["DATABASE_URL"])
