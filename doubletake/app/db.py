"""SQLAlchemy engine/session setup.

The database is a SQLite file stored at ``./data/ledger.db`` relative to the
project root (the directory that contains the ``app`` package).
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Project root == parent of the ``app`` package directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "ledger.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


def get_db():
    """FastAPI dependency that yields a session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables that do not yet exist."""
    from app import models  # noqa: F401  (ensure models are registered)

    Base.metadata.create_all(bind=engine)
