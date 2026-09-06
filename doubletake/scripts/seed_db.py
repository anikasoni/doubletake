"""Populate ``data/ledger.db`` from a seed JSON case file.

Usage (from the project root)::

    python -m scripts.seed_db                       # loads data/seed_cases/case_001.json
    python -m scripts.seed_db path/to/case.json     # loads an explicit file

The database is wiped (all tables dropped and recreated) before the case data is
loaded, so seeding is idempotent for demo purposes.
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

# Make ``app`` importable when this file is run directly (python scripts/seed_db.py).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import models  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402

DEFAULT_CASE = PROJECT_ROOT / "data" / "seed_cases" / "case_001.json"

# Maps the JSON keys in a case file to ORM models, in insertion order.
SECTIONS = [
    ("invoices", models.Invoice),
    ("credit_notes", models.CreditNote),
    ("payments", models.Payment),
    ("remittance_advices", models.RemittanceAdvice),
    ("allocations", models.Allocation),
    ("review_cases", models.ReviewCase),
]

DATE_FIELDS = {"issued_date", "received_date"}
DATETIME_FIELDS = {"created_at"}


def _coerce(row: dict) -> dict:
    """Convert ISO date/datetime strings into Python objects."""
    out = {}
    for key, value in row.items():
        if isinstance(value, str) and key in DATE_FIELDS:
            out[key] = date.fromisoformat(value)
        elif isinstance(value, str) and key in DATETIME_FIELDS:
            out[key] = datetime.fromisoformat(value)
        else:
            out[key] = value
    return out


def load_case(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def seed_database(path: Path | str = DEFAULT_CASE) -> dict[str, int]:
    """Wipe every table and reload it from the given case file.

    Returns a mapping of section name -> number of rows inserted.
    """
    path = Path(path)
    case = load_case(path)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    counts: dict[str, int] = {}
    session = SessionLocal()
    try:
        for section, model in SECTIONS:
            rows = case.get(section, [])
            for row in rows:
                session.add(model(**_coerce(row)))
            counts[section] = len(rows)
        session.commit()
    finally:
        session.close()

    return counts


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_CASE
    if not path.exists():
        print(f"Seed case file not found: {path}", file=sys.stderr)
        return 1
    counts = seed_database(path)
    total = sum(counts.values())
    print(f"Seeded {total} rows from {path}:")
    for section, count in counts.items():
        print(f"  {section}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
