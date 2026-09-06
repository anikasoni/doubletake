"""Tests for :func:`app.candidates.generate_candidates`.

The four scenarios below mirror the customers seeded in
``data/seed_cases/case_001.json``:

* CUST-01 -- clean match
* CUST-02 -- resolvable ambiguity (credit note available)
* CUST-03 -- contradiction case (credit note already consumed elsewhere)
* CUST-04 -- missing evidence (no remittance advice)

Candidate generation is deliberately naive: it only checks that amounts
balance, so CUST-02, CUST-03 and CUST-04 all produce the same two candidates
even though later validation stages would treat them very differently.
"""

import json
from pathlib import Path

import pytest

from app.candidates import generate_candidates
from app.schemas import CreditNoteSchema, InvoiceSchema, PaymentSchema

CASE_PATH = Path(__file__).resolve().parents[1] / "data" / "seed_cases" / "case_001.json"


@pytest.fixture(scope="module")
def case() -> dict:
    with open(CASE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def invoices(case) -> list[InvoiceSchema]:
    return [InvoiceSchema(**row) for row in case["invoices"]]


@pytest.fixture(scope="module")
def credit_notes(case) -> list[CreditNoteSchema]:
    return [CreditNoteSchema(**row) for row in case["credit_notes"]]


@pytest.fixture(scope="module")
def payments(case) -> dict[str, PaymentSchema]:
    return {row["id"]: PaymentSchema(**row) for row in case["payments"]}


def test_cust01_clean_match(payments, invoices, credit_notes):
    result = generate_candidates(payments["PAY-101"], invoices, credit_notes)

    assert len(result) == 1
    (candidate,) = result
    assert candidate.invoice_id == "INV-101"
    assert candidate.match_type == "exact_amount"
    assert candidate.credit_note_id is None
    assert candidate.amount_checks_pass is True


def test_cust02_resolvable_ambiguity(payments, invoices, credit_notes):
    result = generate_candidates(payments["PAY-201"], invoices, credit_notes)

    assert [(c.invoice_id, c.match_type, c.credit_note_id) for c in result] == [
        ("INV-201", "exact_amount", None),
        ("INV-202", "invoice_minus_credit_note", "CN-201"),
    ]
    assert all(c.amount_checks_pass for c in result)


def test_cust03_contradiction_same_shape_as_cust02(payments, invoices, credit_notes):
    # CN-301 is already consumed elsewhere, but candidate generation does not
    # know about consumed status yet -- that is validation's job later.
    result = generate_candidates(payments["PAY-301"], invoices, credit_notes)

    assert [(c.invoice_id, c.match_type, c.credit_note_id) for c in result] == [
        ("INV-301", "exact_amount", None),
        ("INV-302", "invoice_minus_credit_note", "CN-301"),
    ]
    assert all(c.amount_checks_pass for c in result)


def test_cust04_missing_evidence_same_shape(payments, invoices, credit_notes):
    # No remittance advice exists for PAY-401, but that evidence gap is not
    # something candidate generation considers.
    result = generate_candidates(payments["PAY-401"], invoices, credit_notes)

    assert [(c.invoice_id, c.match_type, c.credit_note_id) for c in result] == [
        ("INV-401", "exact_amount", None),
        ("INV-402", "invoice_minus_credit_note", "CN-401"),
    ]
    assert all(c.amount_checks_pass for c in result)


def test_candidates_scoped_to_payment_customer(payments, invoices, credit_notes):
    # PAY-201 (CUST-02) must never match an INV-3xx / INV-4xx invoice even
    # though they share the same amounts.
    result = generate_candidates(payments["PAY-201"], invoices, credit_notes)

    assert {c.invoice_id for c in result} == {"INV-201", "INV-202"}
