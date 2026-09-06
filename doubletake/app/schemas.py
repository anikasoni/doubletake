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
    status: ReviewCaseStatus
    created_at: datetime
