"""SQLAlchemy ORM models for the doubletake ledger."""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

AMOUNT = Numeric(18, 2)


class InvoiceStatus(str, enum.Enum):
    open = "open"
    paid = "paid"
    partially_paid = "partially_paid"


class CreditNoteStatus(str, enum.Enum):
    available = "available"
    consumed = "consumed"


class PaymentStatus(str, enum.Enum):
    unallocated = "unallocated"
    allocated = "allocated"
    under_review = "under_review"


class AllocationStatus(str, enum.Enum):
    applied = "applied"
    proposed = "proposed"


class ReviewCaseStatus(str, enum.Enum):
    pending = "pending"
    resolved = "resolved"


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus), nullable=False, default=InvoiceStatus.open
    )
    issued_date: Mapped[date] = mapped_column(Date, nullable=False)


class CreditNote(Base):
    __tablename__ = "credit_notes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    linked_invoice_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[CreditNoteStatus] = mapped_column(
        Enum(CreditNoteStatus), nullable=False, default=CreditNoteStatus.available
    )
    consumed_by_invoice_id: Mapped[str | None] = mapped_column(String, nullable=True)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), nullable=False, default=PaymentStatus.unallocated
    )


class RemittanceAdvice(Base):
    __tablename__ = "remittance_advices"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payment_id: Mapped[str] = mapped_column(String, nullable=False)
    referenced_invoice_id: Mapped[str | None] = mapped_column(String, nullable=True)
    referenced_credit_note_id: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Allocation(Base):
    __tablename__ = "allocations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payment_id: Mapped[str] = mapped_column(String, nullable=False)
    invoice_id: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    status: Mapped[AllocationStatus] = mapped_column(
        Enum(AllocationStatus), nullable=False, default=AllocationStatus.proposed
    )
    # JSON list of evidence record ids.
    evidence_used: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    decision_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ReviewCase(Base):
    __tablename__ = "review_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payment_id: Mapped[str] = mapped_column(String, nullable=False)
    # JSON structure describing the competing allocation candidates.
    competing_candidates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Evidence the investigator gathered before escalating -- same shape as
    # ``Allocation.evidence_used``. Persisted so the payment-detail endpoint can
    # replay the evidence trail without re-investigating.
    evidence_checked: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Human-readable rationale for why the case was opened (LLM-phrased when it
    # comes out of an investigation, empty otherwise).
    decision_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # True when investigation proved the ledger contradicts itself (e.g. a
    # claimed credit note was already consumed elsewhere).
    contradiction_found: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    status: Mapped[ReviewCaseStatus] = mapped_column(
        Enum(ReviewCaseStatus), nullable=False, default=ReviewCaseStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
