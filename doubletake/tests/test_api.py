"""API contract tests for ``GET /payments/{payment_id}``.

Process a payment, then fetch it again and assert the response carries
everything ``frontend/src/pages/PaymentDetail.tsx`` needs to rebuild the
candidate worksheet, the evidence trail and the outcome banner -- with no
re-processing and no re-seeding.

The single Gemini call the investigator makes is stubbed; no live API is hit.
"""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.investigator as investigator
from app import models
from app.db import Base, get_db
from app.main import app

CASE_PATH = Path(__file__).resolve().parents[1] / "data" / "seed_cases" / "case_001.json"
_DATE_FIELDS = {"issued_date", "received_date"}
_SECTIONS = [
    ("invoices", models.Invoice),
    ("credit_notes", models.CreditNote),
    ("payments", models.Payment),
    ("remittance_advices", models.RemittanceAdvice),
]


def _coerce(row: dict) -> dict:
    return {
        key: (date.fromisoformat(value) if key in _DATE_FIELDS else value)
        for key, value in row.items()
    }


@pytest.fixture
def client(monkeypatch):
    """A ``TestClient`` backed by a fresh in-memory DB seeded from case_001."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with open(CASE_PATH, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    seed = TestingSession()
    for section, model in _SECTIONS:
        for row in case.get(section, []):
            seed.add(model(**_coerce(row)))
    seed.commit()
    seed.close()

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    # Stub the investigator's one Gemini call with a fixed rationale.
    state = {"text": "Rationale placeholder for the API contract test."}

    class _FakeModel:
        def __init__(self, model_name, *, system_instruction=None, **kwargs):
            pass

        def generate_content(self, contents, **kwargs):
            return SimpleNamespace(text=state["text"])

    monkeypatch.setattr(investigator.genai, "configure", lambda **kwargs: None)
    monkeypatch.setattr(investigator.genai, "GenerativeModel", _FakeModel)

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app), state
    finally:
        app.dependency_overrides.clear()


def test_unallocated_payment_has_no_investigation_detail(client):
    c, _ = client
    body = c.get("/payments/PAY-201").json()

    assert body["status"] == "unallocated"
    assert body["candidates"] == []
    assert body["allocation"] is None
    assert body["review_case"] is None


def test_get_after_resolve_reconstructs_full_display(client):
    c, state = client
    state["text"] = (
        "The remittance advice named the deduction candidate and its credit "
        "note was still available, so the payment was allocated to INV-202."
    )

    proc = c.post("/payments/PAY-201/process").json()
    assert proc["outcome"] == "allocated"
    assert proc["selected_invoice_id"] == "INV-202"

    detail = c.get("/payments/PAY-201").json()

    # Base payment fields.
    assert detail["id"] == "PAY-201"
    assert detail["customer_id"] == "CUST-02"
    assert detail["amount"] == "100000.00"
    assert detail["received_date"] == "2026-02-02"
    assert detail["status"] == "allocated"

    # Full candidate worksheet -- winner and loser -- identical to what the
    # process response returned.
    assert detail["candidates"] == proc["competing_candidates"]
    assert [(c_["invoice_id"], c_["match_type"]) for c_ in detail["candidates"]] == [
        ("INV-201", "exact_amount"),
        ("INV-202", "invoice_minus_credit_note"),
    ]

    # Allocation block: everything the accepted row + outcome banner need.
    alloc = detail["allocation"]
    assert alloc["invoice_id"] == "INV-202"
    assert alloc["amount"] == "100000.00"
    assert alloc["decision_rationale"] == state["text"]
    assert [e["evidence_type"] for e in alloc["evidence_used"]] == [
        "remittance_advice",
        "credit_note_status",
    ]
    # Evidence trail content survives the round-trip.
    assert alloc["evidence_used"] == proc["investigation"]["evidence_checked"]
    cn = alloc["evidence_used"][1]
    assert cn["credit_note_id"] == "CN-201"
    assert cn["status"] == "available"

    assert detail["review_case"] is None

    # Outcome banner: "Applied to INV-202. INV-201 remains outstanding."
    others = [
        c_["invoice_id"]
        for c_ in detail["candidates"]
        if c_["invoice_id"] != alloc["invoice_id"]
    ]
    assert others == ["INV-201"]


def test_get_after_escalation_includes_contradiction_evidence(client):
    c, state = client
    state["text"] = (
        "The cited credit note had already been consumed by another invoice, "
        "so the payment was sent for review."
    )

    proc = c.post("/payments/PAY-301/process").json()
    assert proc["outcome"] == "under_review"

    detail = c.get("/payments/PAY-301").json()

    assert detail["status"] == "under_review"
    assert detail["allocation"] is None

    rc = detail["review_case"]
    assert rc["contradiction_found"] is True
    assert rc["decision_rationale"] == state["text"]
    assert rc["status"] == "pending"
    assert [x["invoice_id"] for x in rc["competing_candidates"]] == ["INV-301", "INV-302"]

    # candidates mirrors the stored review-case set.
    assert detail["candidates"] == rc["competing_candidates"]

    # The consumed-credit-note line the evidence trail must show.
    cn = next(
        e for e in rc["evidence_checked"] if e["evidence_type"] == "credit_note_status"
    )
    assert cn["credit_note_id"] == "CN-301"
    assert cn["status"] == "consumed"
    assert cn["consumed_by_invoice_id"] == "INV-999"
    # Identical to what process_payment reported.
    assert rc["evidence_checked"] == proc["investigation"]["evidence_checked"]


def test_get_after_single_candidate_resolve(client):
    c, _ = client
    proc = c.post("/payments/PAY-101/process").json()
    assert proc["path"] == "single_candidate"

    detail = c.get("/payments/PAY-101").json()

    assert detail["status"] == "allocated"
    assert [x["invoice_id"] for x in detail["candidates"]] == ["INV-101"]
    assert detail["candidates"] == proc["competing_candidates"]
    assert detail["allocation"]["invoice_id"] == "INV-101"
    assert detail["allocation"]["evidence_used"] == []
    assert detail["review_case"] is None


def test_get_missing_payment_404(client):
    c, _ = client
    assert c.get("/payments/NOPE").status_code == 404
