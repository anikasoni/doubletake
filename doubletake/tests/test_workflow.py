"""End-to-end tests for :func:`app.workflow.process_payment`.

Each of the four customers seeded in ``data/seed_cases/case_001.json`` exercises
a different branch of the workflow against a real (in-memory) database:

* CUST-01 / PAY-101 -- one balancing candidate -> applied directly, no LLM call.
* CUST-02 / PAY-201 -- two candidates, remittance names the still-available
  credit-note candidate -> investigation ``resolved`` -> applied.
* CUST-03 / PAY-301 -- two candidates, remittance relies on an already-consumed
  credit note -> investigation ``escalate`` with ``contradiction_found``.
* CUST-04 / PAY-401 -- two candidates but no remittance advice on file ->
  investigation ``escalate`` on missing evidence (no contradiction).

The single Anthropic call the investigator makes is stubbed; no live API is hit.
"""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.investigator as investigator
from app import models
from app.db import Base
from app.workflow import process_payment

CASE_PATH = Path(__file__).resolve().parents[1] / "data" / "seed_cases" / "case_001.json"

_DATE_FIELDS = {"issued_date", "received_date"}


@pytest.fixture(scope="module")
def case() -> dict:
    with open(CASE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _coerce(row: dict) -> dict:
    return {
        key: (date.fromisoformat(value) if key in _DATE_FIELDS else value)
        for key, value in row.items()
    }


@pytest.fixture
def db_session(case):
    """A fresh in-memory database seeded from case_001.json."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    for row in case["invoices"]:
        session.add(models.Invoice(**_coerce(row)))
    for row in case["credit_notes"]:
        session.add(models.CreditNote(**_coerce(row)))
    for row in case["payments"]:
        session.add(models.Payment(**_coerce(row)))
    for row in case["remittance_advices"]:
        session.add(models.RemittanceAdvice(**_coerce(row)))
    session.commit()

    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def anthropic_stub(monkeypatch):
    """Replace ``anthropic.Anthropic`` with a fake returning a fixed string."""
    state = {"text": "Deterministic outcome; rationale placeholder.", "calls": []}

    class _FakeMessages:
        def create(self, **kwargs):
            state["calls"].append(kwargs)
            block = SimpleNamespace(type="text", text=state["text"])
            return SimpleNamespace(content=[block])

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.messages = _FakeMessages()

    monkeypatch.setattr(investigator.anthropic, "Anthropic", _FakeClient)
    return state


# --------------------------------------------------------------------------- #
# CUST-01 -- single candidate, applied directly                               #
# --------------------------------------------------------------------------- #


def test_cust01_single_candidate_applies_directly(db_session, anthropic_stub):
    summary = process_payment("PAY-101", db_session)

    assert summary["path"] == "single_candidate"
    assert summary["outcome"] == "allocated"
    assert summary["candidate_count"] == 1
    assert summary["selected_invoice_id"] == "INV-101"
    assert summary["investigation"] is None
    # No ambiguity -> the investigator (and its Anthropic call) never runs.
    assert anthropic_stub["calls"] == []

    allocation = db_session.get(models.Allocation, summary["allocation_id"])
    assert allocation is not None
    assert allocation.invoice_id == "INV-101"
    assert allocation.status is models.AllocationStatus.applied
    assert str(allocation.amount) == "50000.00"

    assert db_session.get(models.Invoice, "INV-101").status is models.InvoiceStatus.paid
    assert db_session.get(models.Payment, "PAY-101").status is models.PaymentStatus.allocated
    assert db_session.query(models.ReviewCase).count() == 0


# --------------------------------------------------------------------------- #
# CUST-02 -- ambiguous, resolved by investigation                             #
# --------------------------------------------------------------------------- #


def test_cust02_resolves_via_investigation(db_session, anthropic_stub):
    anthropic_stub["text"] = (
        "The remittance advice names the invoice-minus-credit-note candidate and "
        "the cited credit note is still available, so the payment is allocated."
    )

    summary = process_payment("PAY-201", db_session)

    assert summary["path"] == "investigated"
    assert summary["outcome"] == "allocated"
    assert summary["candidate_count"] == 2
    assert summary["selected_invoice_id"] == "INV-202"
    assert summary["investigation"]["status"] == "resolved"
    assert summary["investigation"]["contradiction_found"] is False
    assert len(anthropic_stub["calls"]) == 1

    allocation = db_session.get(models.Allocation, summary["allocation_id"])
    assert allocation.invoice_id == "INV-202"
    assert allocation.status is models.AllocationStatus.applied
    assert allocation.decision_rationale == anthropic_stub["text"]
    evidence_types = [e["evidence_type"] for e in allocation.evidence_used]
    assert evidence_types == ["remittance_advice", "credit_note_status"]

    assert db_session.get(models.Invoice, "INV-202").status is models.InvoiceStatus.paid
    assert db_session.get(models.Payment, "PAY-201").status is models.PaymentStatus.allocated
    assert db_session.query(models.ReviewCase).count() == 0


# --------------------------------------------------------------------------- #
# CUST-03 -- ambiguous, escalated with a proven contradiction                 #
# --------------------------------------------------------------------------- #


def test_cust03_escalates_with_contradiction(db_session, anthropic_stub):
    anthropic_stub["text"] = (
        "The remittance relies on a credit note that was already consumed by "
        "another invoice, so the case is escalated."
    )

    summary = process_payment("PAY-301", db_session)

    assert summary["path"] == "investigated"
    assert summary["outcome"] == "under_review"
    assert summary["selected_invoice_id"] is None
    assert summary["allocation_id"] is None
    assert summary["investigation"]["status"] == "escalate"
    assert summary["investigation"]["contradiction_found"] is True
    assert len(anthropic_stub["calls"]) == 1

    review = db_session.get(models.ReviewCase, summary["review_case_id"])
    assert review is not None
    assert review.payment_id == "PAY-301"
    assert review.contradiction_found is True
    assert review.decision_rationale == anthropic_stub["text"]
    assert [c["invoice_id"] for c in review.competing_candidates] == [
        "INV-301",
        "INV-302",
    ]
    assert review.status is models.ReviewCaseStatus.pending

    assert db_session.get(models.Payment, "PAY-301").status is models.PaymentStatus.under_review
    assert db_session.query(models.Allocation).count() == 0
    assert db_session.get(models.Invoice, "INV-301").status is models.InvoiceStatus.open
    assert db_session.get(models.Invoice, "INV-302").status is models.InvoiceStatus.open


# --------------------------------------------------------------------------- #
# CUST-04 -- ambiguous, escalated on missing evidence (no contradiction)      #
# --------------------------------------------------------------------------- #


def test_cust04_escalates_on_missing_evidence(db_session, anthropic_stub):
    anthropic_stub["text"] = (
        "There is a missing remittance advice for this payment, so the intended "
        "invoice cannot be confirmed and the case is escalated."
    )

    summary = process_payment("PAY-401", db_session)

    assert summary["path"] == "investigated"
    assert summary["outcome"] == "under_review"
    assert summary["selected_invoice_id"] is None
    assert summary["investigation"]["status"] == "escalate"
    assert summary["investigation"]["contradiction_found"] is False
    assert len(anthropic_stub["calls"]) == 1

    review = db_session.get(models.ReviewCase, summary["review_case_id"])
    assert review.payment_id == "PAY-401"
    assert review.contradiction_found is False
    assert review.reason == "ambiguous allocation could not be resolved automatically"
    assert [c["invoice_id"] for c in review.competing_candidates] == [
        "INV-401",
        "INV-402",
    ]
    assert len(review.decision_rationale) > 0

    assert db_session.get(models.Payment, "PAY-401").status is models.PaymentStatus.under_review
    assert db_session.query(models.Allocation).count() == 0


# --------------------------------------------------------------------------- #
# 0 candidates -- nothing balances -> review case, no LLM call                #
# --------------------------------------------------------------------------- #


def test_no_candidates_opens_review_case(db_session, anthropic_stub):
    # Nudge the payment so it no longer matches any open invoice for CUST-01.
    payment = db_session.get(models.Payment, "PAY-101")
    payment.amount = 12345.67
    db_session.commit()

    summary = process_payment("PAY-101", db_session)

    assert summary["path"] == "no_candidates"
    assert summary["outcome"] == "under_review"
    assert summary["candidate_count"] == 0
    assert summary["allocation_id"] is None
    assert summary["investigation"] is None
    assert anthropic_stub["calls"] == []

    review = db_session.get(models.ReviewCase, summary["review_case_id"])
    assert review.reason == "no balancing invoice found"
    assert review.competing_candidates == []
    assert review.contradiction_found is False
    assert db_session.get(models.Payment, "PAY-101").status is models.PaymentStatus.under_review
