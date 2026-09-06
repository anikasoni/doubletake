"""FastAPI application entrypoint for doubletake."""

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.candidates import generate_candidates
from app.db import get_db, init_db
from app.models import (
    Allocation,
    CreditNote,
    Invoice,
    Payment,
    PaymentStatus,
    ReviewCase,
)
from app.schemas import PaymentDetailSchema, PaymentSchema
from app.workflow import process_payment

# Make the ``scripts`` package importable (it lives next to ``app``).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.seed_db import DEFAULT_CASE, seed_database  # noqa: E402

app = FastAPI(title="doubletake")

# Allow the Vite dev server (frontend/) to call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/payments", response_model=list[PaymentSchema])
def list_payments(db: Session = Depends(get_db)) -> list[Payment]:
    """List every payment with its customer, amount and allocation status."""
    return db.query(Payment).order_by(Payment.id).all()


def _evaluated_candidates(
    db: Session, payment: Payment, allocation: Allocation | None
) -> list[dict]:
    """Re-derive the full candidate set that ``process_payment`` evaluated.

    ``generate_candidates`` only considers ``open`` invoices, so for a resolved
    payment the settled invoice (now ``paid``) is viewed as ``open`` again --
    the workflow never touches any other invoice or credit note, so this
    reproduces the exact set that was weighed.
    """
    invoices = (
        db.query(Invoice).filter(Invoice.customer_id == payment.customer_id).all()
    )
    credit_notes = (
        db.query(CreditNote)
        .filter(CreditNote.customer_id == payment.customer_id)
        .all()
    )
    if allocation is not None:
        invoices = [
            SimpleNamespace(
                id=inv.id,
                customer_id=inv.customer_id,
                amount=inv.amount,
                status="open" if inv.id == allocation.invoice_id else inv.status,
            )
            for inv in invoices
        ]
    return [
        {
            "invoice_id": c.invoice_id,
            "match_type": c.match_type,
            "credit_note_id": c.credit_note_id,
        }
        for c in generate_candidates(payment, invoices, credit_notes)
    ]


@app.get("/payments/{payment_id}", response_model=PaymentDetailSchema)
def get_payment(payment_id: str, db: Session = Depends(get_db)) -> dict:
    """Return a payment and, once it has been processed, its full investigation
    detail: the evaluated candidate set, the applied allocation or the open
    review case. Enough for the UI to rebuild the worksheet, evidence trail and
    outcome banner with no re-processing.
    """
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail=f"payment {payment_id!r} not found")

    detail: dict = {
        "id": payment.id,
        "customer_id": payment.customer_id,
        "amount": payment.amount,
        "received_date": payment.received_date,
        "status": payment.status,
        "candidates": [],
        "allocation": None,
        "review_case": None,
    }
    if payment.status == PaymentStatus.unallocated:
        return detail

    allocation = (
        db.query(Allocation).filter(Allocation.payment_id == payment_id).first()
    )
    review_case = (
        db.query(ReviewCase).filter(ReviewCase.payment_id == payment_id).first()
    )

    if allocation is not None:
        detail["allocation"] = {
            "invoice_id": allocation.invoice_id,
            "amount": allocation.amount,
            "evidence_used": allocation.evidence_used,
            "decision_rationale": allocation.decision_rationale,
        }
    if review_case is not None:
        detail["review_case"] = {
            "competing_candidates": review_case.competing_candidates,
            "decision_rationale": review_case.decision_rationale,
            "contradiction_found": review_case.contradiction_found,
            "evidence_checked": review_case.evidence_checked,
            "status": review_case.status,
        }

    # An escalated case stored the candidate set verbatim; otherwise re-derive it.
    if review_case is not None and review_case.competing_candidates:
        detail["candidates"] = review_case.competing_candidates
    else:
        detail["candidates"] = _evaluated_candidates(db, payment, allocation)

    return detail


@app.post("/payments/{payment_id}/process")
def process_payment_endpoint(
    payment_id: str, db: Session = Depends(get_db)
) -> dict:
    """Run the allocation workflow for one payment and return a summary."""
    try:
        return process_payment(payment_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
