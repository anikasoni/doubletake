"""End-to-end payment allocation workflow.

This module glues together the deterministic building blocks:

1. :func:`app.candidates.generate_candidates` enumerates the ways a payment can
   balance against the customer's open invoices.
2. Depending on how many candidates come back:

   * **0 candidates** -- nothing balances, so a :class:`~app.models.ReviewCase`
     is opened and the payment is parked ``under_review``.
   * **1 candidate** -- unambiguous, so it is applied directly: an
     :class:`~app.models.Allocation` is written, the invoice is marked
     ``paid`` and the payment ``allocated``.
   * **>1 candidate** -- ambiguous, so :func:`app.investigator.investigate`
     runs. If it ``resolved`` the ambiguity the selected candidate is applied
     exactly as the single-candidate case; if it wants to ``escalate`` a
     :class:`~app.models.ReviewCase` is opened carrying the investigation's
     rationale, competing candidates and contradiction flag.

The only external call in the whole path is the single Anthropic request made
by the investigator to phrase its rationale; everything else is plain Python.
"""

from __future__ import annotations

from app.candidates import Candidate, generate_candidates
from app.investigator import investigate
from app.models import (
    Allocation,
    AllocationStatus,
    CreditNote,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentStatus,
    ReviewCase,
    ReviewCaseStatus,
)

NO_CANDIDATE_REASON = "no balancing invoice found"
ESCALATION_REASON = "ambiguous allocation could not be resolved automatically"


def _candidate_dict(candidate: Candidate) -> dict:
    """Serialise a candidate for storage in a review case."""
    return {
        "invoice_id": candidate.invoice_id,
        "match_type": candidate.match_type,
        "credit_note_id": candidate.credit_note_id,
    }


def _allocation_id(payment_id: str) -> str:
    return f"ALLOC-{payment_id}"


def _review_case_id(payment_id: str) -> str:
    return f"RC-{payment_id}"


def _apply_candidate(
    db_session,
    payment: Payment,
    candidate: Candidate,
    *,
    evidence_used: list,
    decision_rationale: str,
) -> Allocation:
    """Write an ``applied`` allocation and roll the invoice/payment forward.

    Full settlement is assumed for now: an ``invoice_minus_credit_note``
    candidate is treated as fully closing the invoice (the linked credit note
    covers the shortfall), so the invoice always ends up ``paid`` rather than
    ``partially_paid``.
    """
    invoice = db_session.get(Invoice, candidate.invoice_id)

    allocation = Allocation(
        id=_allocation_id(payment.id),
        payment_id=payment.id,
        invoice_id=invoice.id,
        amount=payment.amount,
        status=AllocationStatus.applied,
        evidence_used=evidence_used,
        decision_rationale=decision_rationale,
    )
    db_session.add(allocation)

    # A candidate only exists because its arithmetic already balances to the
    # invoice total (the payment on its own, or the payment plus a linked
    # credit note), so the invoice is fully closed. Partial settlement -- where
    # the invoice would move to ``partially_paid`` instead -- is deferred until
    # the workflow handles under-payments.
    invoice.status = InvoiceStatus.paid
    payment.status = PaymentStatus.allocated
    return allocation


def process_payment(payment_id, db_session) -> dict:
    """Run the full allocation workflow for one payment.

    Args:
        payment_id: primary key of the :class:`~app.models.Payment` to process.
        db_session: a SQLAlchemy session; it is committed by this function.

    Returns:
        A summary dict describing what happened. Always contains ``payment_id``,
        ``path`` (``no_candidates`` / ``single_candidate`` / ``investigated``),
        ``outcome`` (``allocated`` / ``under_review``) and ``candidate_count``.
    """
    payment = db_session.get(Payment, payment_id)
    if payment is None:
        raise ValueError(f"payment {payment_id!r} not found")

    invoices = (
        db_session.query(Invoice)
        .filter(Invoice.customer_id == payment.customer_id)
        .all()
    )
    credit_notes = (
        db_session.query(CreditNote)
        .filter(CreditNote.customer_id == payment.customer_id)
        .all()
    )

    candidates = generate_candidates(payment, invoices, credit_notes)

    # --- 0 candidates: nothing balances -----------------------------------
    if not candidates:
        review = ReviewCase(
            id=_review_case_id(payment_id),
            payment_id=payment_id,
            competing_candidates=[],
            reason=NO_CANDIDATE_REASON,
            decision_rationale="",
            contradiction_found=False,
            status=ReviewCaseStatus.pending,
        )
        db_session.add(review)
        payment.status = PaymentStatus.under_review
        db_session.commit()
        return {
            "payment_id": payment_id,
            "path": "no_candidates",
            "outcome": "under_review",
            "candidate_count": 0,
            "selected_invoice_id": None,
            "allocation_id": None,
            "review_case_id": review.id,
            "review_reason": NO_CANDIDATE_REASON,
            "investigation": None,
        }

    # --- 1 candidate: unambiguous, apply directly ------------------------
    if len(candidates) == 1:
        candidate = candidates[0]
        allocation = _apply_candidate(
            db_session,
            payment,
            candidate,
            evidence_used=[],
            decision_rationale="single balancing candidate; applied automatically",
        )
        db_session.commit()
        return {
            "payment_id": payment_id,
            "path": "single_candidate",
            "outcome": "allocated",
            "candidate_count": 1,
            "selected_invoice_id": candidate.invoice_id,
            "allocation_id": allocation.id,
            "review_case_id": None,
            "investigation": None,
        }

    # --- >1 candidate: ambiguous, investigate ---------------------------
    result = investigate(payment, candidates, db_session)
    investigation_summary = {
        "status": result.status,
        "selected_invoice_id": result.selected_invoice_id,
        "contradiction_found": result.contradiction_found,
        "decision_rationale": result.decision_rationale,
        "evidence_checked": result.evidence_checked,
    }

    if result.status == "resolved":
        candidate = next(
            c for c in candidates if c.invoice_id == result.selected_invoice_id
        )
        allocation = _apply_candidate(
            db_session,
            payment,
            candidate,
            evidence_used=result.evidence_checked,
            decision_rationale=result.decision_rationale,
        )
        db_session.commit()
        return {
            "payment_id": payment_id,
            "path": "investigated",
            "outcome": "allocated",
            "candidate_count": len(candidates),
            "selected_invoice_id": candidate.invoice_id,
            "allocation_id": allocation.id,
            "review_case_id": None,
            "investigation": investigation_summary,
        }

    # status == "escalate"
    review = ReviewCase(
        id=_review_case_id(payment_id),
        payment_id=payment_id,
        competing_candidates=[_candidate_dict(c) for c in candidates],
        reason=ESCALATION_REASON,
        decision_rationale=result.decision_rationale,
        contradiction_found=result.contradiction_found,
        status=ReviewCaseStatus.pending,
    )
    db_session.add(review)
    payment.status = PaymentStatus.under_review
    db_session.commit()
    return {
        "payment_id": payment_id,
        "path": "investigated",
        "outcome": "under_review",
        "candidate_count": len(candidates),
        "selected_invoice_id": None,
        "allocation_id": None,
        "review_case_id": review.id,
        "review_reason": ESCALATION_REASON,
        "investigation": investigation_summary,
    }
