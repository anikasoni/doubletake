"""Pydantic schemas mirroring the ORM models for API input/output."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models import (
    AllocationStatus,
    CreditNoteStatus,
    InvoiceStatus,
    PaymentStatus,
    ReviewCaseStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class InvoiceSchema(ORMModel):
    id: str
    customer_id: str
    amount: Decimal
    status: InvoiceStatus
    issued_date: date


class CreditNoteSchema(ORMModel):
    id: str
    customer_id: str
    amount: Decimal
    linked_invoice_id: str | None = None
    status: CreditNoteStatus
    consumed_by_invoice_id: str | None = None


class PaymentSchema(ORMModel):
    id: str
    customer_id: str
    amount: Decimal
    received_date: date
    status: PaymentStatus


class RemittanceAdviceSchema(ORMModel):
    id: str
    payment_id: str
    referenced_invoice_id: str | None = None
    referenced_credit_note_id: str | None = None
    raw_text: str


class AllocationSchema(ORMModel):
    id: str
    payment_id: str
    invoice_id: str
    amount: Decimal
    status: AllocationStatus
    evidence_used: list
    created_at: datetime
    decision_rationale: str


class ReviewCaseSchema(ORMModel):
    id: str
    payment_id: str
    competing_candidates: list
    reason: str
    decision_rationale: str
    contradiction_found: bool
    status: ReviewCaseStatus
    created_at: datetime


class CandidateSchema(BaseModel):
    """One balancing allocation candidate -- the shape ``process_payment``
    returns in ``competing_candidates`` and stores on a review case."""

    invoice_id: str
    match_type: str
    credit_note_id: str | None = None


class PaymentAllocationSchema(ORMModel):
    """The applied allocation for a payment that resolved."""

    invoice_id: str
    amount: Decimal
    evidence_used: list
    decision_rationale: str


class PaymentReviewCaseSchema(ORMModel):
    """The open review case for a payment that escalated."""

    competing_candidates: list
    decision_rationale: str
    contradiction_found: bool
    evidence_checked: list
    status: ReviewCaseStatus


class PaymentDetailSchema(ORMModel):
    """A payment plus -- once it has been processed -- the full investigation
    detail the UI needs to reconstruct the candidate worksheet, evidence trail
    and outcome banner without re-processing.

    ``candidates`` is always the full set that was evaluated (winners and
    losers); ``allocation`` is set iff the payment resolved; ``review_case`` is
    set iff it escalated. For an ``unallocated`` payment all three are empty.
    """

    id: str
    customer_id: str
    amount: Decimal
    received_date: date
    status: PaymentStatus
    candidates: list[CandidateSchema] = []
    allocation: PaymentAllocationSchema | None = None
    review_case: PaymentReviewCaseSchema | None = None
