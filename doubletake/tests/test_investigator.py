"""Tests for :mod:`app.investigator`.

The three headline scenarios mirror the customers seeded in
``data/seed_cases/case_001.json`` and exercise the *real* deterministic flow
against a real (in-memory) database:

* CUST-02 / PAY-201 -- resolvable ambiguity: remittance names the deduction
  candidate and its credit note is still available -> ``resolved`` on INV-202.
* CUST-03 / PAY-301 -- contradiction: remittance names a deduction candidate
  whose credit note was already consumed elsewhere -> ``escalate``.
* CUST-04 / PAY-401 -- missing evidence: no remittance advice on file ->
  ``escalate``.

The Anthropic call is stubbed to return a fixed string; no live API is hit.
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
from app.candidates import generate_candidates
from app.db import Base
from app.investigator import (
    check_credit_note_status,
    fetch_remittance_advice,
    investigate,
    rank_evidence_options,
)

CASE_PATH = Path(__file__).resolve().parents[1] / "data" / "seed_cases" / "case_001.json"
CASE_002_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "seed_cases" / "case_002.json"
)

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
    """Replace ``anthropic.Anthropic`` with a fake that returns a fixed string.

    The test sets ``state["text"]`` to control the rationale and reads
    ``state["calls"]`` to assert exactly one call was made.
    """
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


def _payment_and_candidates(session, payment_id: str):
    payment = session.get(models.Payment, payment_id)
    invoices = session.query(models.Invoice).all()
    credit_notes = session.query(models.CreditNote).all()
    return payment, generate_candidates(payment, invoices, credit_notes)


def _seed_customer_block(block: dict):
    """Seed a fresh in-memory DB from a single ``case_002.json`` customer block."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    for row in block.get("invoices", []):
        session.add(models.Invoice(**_coerce(row)))
    for row in block.get("credit_notes", []):
        session.add(models.CreditNote(**_coerce(row)))
    for row in block.get("payments", []):
        session.add(models.Payment(**_coerce(row)))
    for row in block.get("remittance_advices", []):
        session.add(models.RemittanceAdvice(**_coerce(row)))
    session.commit()
    return session


# --------------------------------------------------------------------------- #
# Headline scenarios                                                          #
# --------------------------------------------------------------------------- #


def test_cust02_resolves_to_inv202(db_session, anthropic_stub):
    anthropic_stub["text"] = (
        "The remittance advice names the invoice-minus-credit-note candidate and "
        "the cited credit note is still available, so the payment is allocated."
    )
    payment, candidates = _payment_and_candidates(db_session, "PAY-201")
    assert len(candidates) > 1

    result = investigate(payment, candidates, db_session)

    assert result.status == "resolved"
    assert result.selected_invoice_id == "INV-202"
    assert result.contradiction_found is False
    assert len(anthropic_stub["calls"]) == 1
    assert anthropic_stub["calls"][0]["model"] == "claude-sonnet-4-6"

    evidence_types = [e["evidence_type"] for e in result.evidence_checked]
    assert evidence_types == ["remittance_advice", "credit_note_status"]
    cn_evidence = result.evidence_checked[1]
    assert cn_evidence["credit_note_id"] == "CN-201"
    assert cn_evidence["status"] == "available"


def test_cust03_escalates_on_consumed_credit_note(db_session, anthropic_stub):
    anthropic_stub["text"] = (
        "The remittance relies on a credit note that was already consumed by "
        "another invoice; because the consumed credit note cannot be reused, the "
        "case is escalated."
    )
    payment, candidates = _payment_and_candidates(db_session, "PAY-301")
    assert len(candidates) > 1

    result = investigate(payment, candidates, db_session)

    assert result.status == "escalate"
    assert result.selected_invoice_id is None
    assert result.contradiction_found is True
    assert "consumed credit note" in result.decision_rationale.lower()
    assert len(anthropic_stub["calls"]) == 1

    cn_evidence = next(
        e for e in result.evidence_checked if e["evidence_type"] == "credit_note_status"
    )
    assert cn_evidence["credit_note_id"] == "CN-301"
    assert cn_evidence["status"] == "consumed"
    assert cn_evidence["consumed_by_invoice_id"] == "INV-999"


def test_cust04_escalates_on_missing_remittance(db_session, anthropic_stub):
    anthropic_stub["text"] = (
        "There is a missing remittance advice for this payment, so the intended "
        "invoice cannot be confirmed and the case is escalated."
    )
    payment, candidates = _payment_and_candidates(db_session, "PAY-401")
    assert len(candidates) > 1

    result = investigate(payment, candidates, db_session)

    assert result.status == "escalate"
    assert result.selected_invoice_id is None
    assert result.contradiction_found is False
    assert "missing remittance" in result.decision_rationale.lower()
    assert len(anthropic_stub["calls"]) == 1

    assert len(result.evidence_checked) == 1
    ra_evidence = result.evidence_checked[0]
    assert ra_evidence["evidence_type"] == "remittance_advice"
    assert ra_evidence["found"] is False


def test_escalates_without_contradiction_when_remittance_names_non_candidate(
    db_session, anthropic_stub
):
    # PAY-401 has candidates INV-401 / INV-402; point its remittance at an
    # invoice that is not a candidate at all.
    db_session.add(
        models.RemittanceAdvice(
            id="RA-401",
            payment_id="PAY-401",
            referenced_invoice_id="INV-999",
            referenced_credit_note_id=None,
            raw_text="Remittance for PAY-401: settles INV-999.",
        )
    )
    db_session.commit()

    anthropic_stub["text"] = (
        "The remittance advice names an invoice that is not one of the balancing "
        "candidates, so the intended allocation cannot be confirmed and the case "
        "is escalated."
    )
    payment, candidates = _payment_and_candidates(db_session, "PAY-401")
    assert len(candidates) > 1

    result = investigate(payment, candidates, db_session)

    assert result.status == "escalate"
    assert result.selected_invoice_id is None
    assert result.contradiction_found is False
    assert len(anthropic_stub["calls"]) == 1

    evidence_types = [e["evidence_type"] for e in result.evidence_checked]
    assert evidence_types == ["remittance_advice"]
    assert result.evidence_checked[0]["found"] is True
    assert result.evidence_checked[0]["referenced_invoice_id"] == "INV-999"


def test_escalates_with_contradiction_when_remittance_cites_mismatched_credit_note(
    anthropic_stub,
):
    """CUST-13 from case_002.json: the remittance references INV-1302 but cites
    CN-1301B, a credit note linked to an unrelated invoice rather than to
    INV-1302 (whose real linked note is CN-1301A). The cited evidence does not
    support the referenced invoice, so the case escalates as a contradiction
    instead of silently allocating against CN-1301A.
    """
    with open(CASE_002_PATH, "r", encoding="utf-8") as fh:
        case_002 = json.load(fh)
    block = next(
        b for b in case_002["customers"] if b["customer_id"] == "CUST-13"
    )

    anthropic_stub["text"] = (
        "The remittance cited credit note CN-1301B, which does not match "
        "CN-1301A, the credit note actually linked to candidate invoice "
        "INV-1302, so the referenced evidence does not support the referenced "
        "invoice and the case is escalated."
    )

    session = _seed_customer_block(block)
    try:
        payment, candidates = _payment_and_candidates(session, "PAY-1301")
        assert len(candidates) > 1

        result = investigate(payment, candidates, session)
    finally:
        session.close()

    assert result.status == "escalate"
    assert result.selected_invoice_id is None
    assert result.contradiction_found is True
    assert len(anthropic_stub["calls"]) == 1

    # The deterministic outcome must surface both credit note IDs -- the one the
    # remittance cited and the one actually linked to the candidate -- to the
    # rationale writer, and the resulting rationale names them.
    facts = anthropic_stub["calls"][0]["messages"][0]["content"]
    assert "CN-1301B" in facts  # cited by the remittance
    assert "CN-1301A" in facts  # actually linked to the candidate invoice
    assert "CN-1301B" in result.decision_rationale
    assert "CN-1301A" in result.decision_rationale

    cn_evidence = next(
        e
        for e in result.evidence_checked
        if e["evidence_type"] == "credit_note_status"
    )
    assert cn_evidence["credit_note_id"] == "CN-1301B"
    assert cn_evidence["status"] is None
    assert "CN-1301A" in cn_evidence["detail"]


# --------------------------------------------------------------------------- #
# Building blocks                                                             #
# --------------------------------------------------------------------------- #


def test_rank_evidence_options_is_fixed_order():
    ranked = rank_evidence_options([])
    assert [opt["evidence_type"] for opt in ranked] == [
        "remittance_advice",
        "credit_note_status",
    ]
    assert ranked[0]["reason"] == (
        "would directly indicate which invoice the customer intended to pay"
    )
    assert ranked[1]["reason"] == (
        "would confirm whether the claimed credit is still valid"
    )


def test_fetch_remittance_advice(db_session):
    assert fetch_remittance_advice("PAY-201", db_session).referenced_invoice_id == "INV-202"
    assert fetch_remittance_advice("PAY-401", db_session) is None


def test_check_credit_note_status(db_session):
    available = check_credit_note_status("CN-201", db_session)
    assert available == {
        "id": "CN-201",
        "status": "available",
        "consumed_by_invoice_id": None,
    }
    consumed = check_credit_note_status("CN-301", db_session)
    assert consumed == {
        "id": "CN-301",
        "status": "consumed",
        "consumed_by_invoice_id": "INV-999",
    }
    missing = check_credit_note_status("CN-DOES-NOT-EXIST", db_session)
    assert missing["status"] is None


def test_investigate_rejects_single_candidate(db_session, anthropic_stub):
    payment, candidates = _payment_and_candidates(db_session, "PAY-101")
    assert len(candidates) == 1
    with pytest.raises(ValueError):
        investigate(payment, candidates, db_session)
    assert anthropic_stub["calls"] == []
