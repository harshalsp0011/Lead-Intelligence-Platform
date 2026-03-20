from __future__ import annotations

"""Database connection and migration helpers.

This file creates the PostgreSQL engine and database sessions for the app.
Other modules use it to open DB sessions, check whether the database is up,
and run the SQL migration files in the database/migrations folder.
"""

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,   # test connection before use — drops stale SSL connections silently
    pool_recycle=300,     # recycle connections every 5 min (before RDS idle timeout)
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def get_db() -> Session:
    """Return a database session."""
    return SessionLocal()


def run_migrations() -> None:
    """Run SQL migration files in numeric order."""
    migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"), key=lambda path: path.name)

    with engine.begin() as connection:
        for migration_file in migration_files:
            sql = migration_file.read_text(encoding="utf-8").strip()
            if sql:
                connection.exec_driver_sql(sql)


def check_connection() -> bool:
    """Return True when the database is reachable, otherwise False."""
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
        return True
    except Exception:
        return False