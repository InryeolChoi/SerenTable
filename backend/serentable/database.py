import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError


class DatabaseNotConfigured(SQLAlchemyError):
    """DATABASE_URL is absent; handled like any other storage failure."""


@lru_cache(maxsize=4)
def engine_for(url: str):
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL is required")
    parsed = parsed.set(drivername="postgresql+psycopg")
    return create_engine(parsed, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def database_engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise DatabaseNotConfigured("DATABASE_URL is not set")
    return engine_for(url)
