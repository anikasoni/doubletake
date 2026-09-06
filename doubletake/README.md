# doubletake

A FastAPI service backed by SQLite for tracking invoices, credit notes, payments,
remittance advice, allocations, and review cases.

## Project structure

```
doubletake/
  app/
    __init__.py
    main.py              # FastAPI app entrypoint
    models.py            # SQLAlchemy models
    schemas.py           # Pydantic schemas for API IO
    db.py                # SQLAlchemy engine/session setup (SQLite at ./data/ledger.db)
  data/
    seed_cases/          # JSON test cases (e.g. case_001.json)
  scripts/
    seed_db.py           # populates ledger.db from a seed JSON case file
  requirements.txt
  README.md
```

## Setup

Run all commands from the `doubletake/` project directory.

```
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

For development and running the tests, install the dev extras instead:

```
pip install -r requirements-dev.txt
```

## Run the tests

```
pytest
```

## Run the API

```
uvicorn app.main:app --reload
```

The service listens on http://127.0.0.1:8000. Interactive docs are at
http://127.0.0.1:8000/docs.

## Endpoints

- `GET /health` — returns `{"status": "ok"}`.
- `POST /seed` — wipes the database and reloads it from
  `data/seed_cases/case_001.json` (for demo purposes).

## Seed the database from the command line

```
python -m scripts.seed_db                      # loads data/seed_cases/case_001.json
python -m scripts.seed_db path/to/case.json    # loads an explicit case file
```

The database file is created automatically at `data/ledger.db`.
