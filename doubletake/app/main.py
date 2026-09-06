"""FastAPI application entrypoint for doubletake."""

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.db import init_db

# Make the ``scripts`` package importable (it lives next to ``app``).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.seed_db import DEFAULT_CASE, seed_database  # noqa: E402

app = FastAPI(title="doubletake")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/seed")
def seed() -> dict:
    """Wipe the database and reload it from ``data/seed_cases/case_001.json``."""
    if not DEFAULT_CASE.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Seed case file not found: {DEFAULT_CASE}",
        )
    counts = seed_database(DEFAULT_CASE)
    return {"status": "seeded", "source": DEFAULT_CASE.name, "counts": counts}
