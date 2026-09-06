"""Deterministic allocation-candidate generation.

This module contains *pure* code only: given a payment and the surrounding
ledger objects it enumerates the ways the payment could balance against open
invoices. It performs no I/O, no database access, and no LLM calls.

A "candidate" is a proposed link between one payment and one invoice that
balances to the exact payment amount, either:

* ``exact_amount`` -- the open invoice amount equals the payment amount, or
* ``invoice_minus_credit_note`` -- the open invoice amount minus a credit note
  linked to that invoice equals the payment amount.

Whether a credit note is actually *usable* (e.g. already consumed elsewhere) is
deliberately **not** decided here -- that is validation's job in a later stage.
Candidate generation only checks that the arithmetic balances.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Literal

from pydantic import BaseModel

MatchType = Literal["exact_amount", "invoice_minus_credit_note"]


class Candidate(BaseModel):
    """A single balancing proposal for a payment against one invoice."""

    invoice_id: str
    match_type: MatchType
    credit_note_id: str | None = None
    # Always True for a returned candidate: we only ever emit candidates whose
    # amounts balance exactly.
    amount_checks_pass: bool = True


def _dec(value) -> Decimal:
    """Coerce an amount to :class:`~decimal.Decimal` for exact comparison."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _status_value(status) -> str:
    """Return the plain string value of an enum-or-string status field."""
    return getattr(status, "value", status)


def generate_candidates(
    payment,
    invoices: Iterable,
    credit_notes: Iterable,
) -> list[Candidate]:
    """Enumerate every balancing allocation candidate for ``payment``.

    Args:
        payment: object with ``amount`` and ``customer_id`` attributes.
        invoices: iterable of objects with ``id``, ``customer_id``, ``amount``
            and ``status`` attributes.
        credit_notes: iterable of objects with ``id``, ``amount`` and
            ``linked_invoice_id`` attributes.

    Returns:
        Candidates sorted by ``(invoice_id, match_type)`` for determinism.
    """
    pay_amount = _dec(payment.amount)

    # Only invoices belonging to the same customer as the payment are eligible.
    open_invoices = [
        inv
        for inv in invoices
        if inv.customer_id == payment.customer_id
        and _status_value(inv.status) == "open"
    ]

    credit_notes = list(credit_notes)
    candidates: list[Candidate] = []

    for invoice in open_invoices:
        invoice_amount = _dec(invoice.amount)

        # exact_amount: the open invoice on its own settles the payment.
        if invoice_amount == pay_amount:
            candidates.append(
                Candidate(invoice_id=invoice.id, match_type="exact_amount")
            )

        # invoice_minus_credit_note: invoice less a linked credit note balances.
        for note in credit_notes:
            if note.linked_invoice_id != invoice.id:
                continue
            if invoice_amount - _dec(note.amount) == pay_amount:
                candidates.append(
                    Candidate(
                        invoice_id=invoice.id,
                        match_type="invoice_minus_credit_note",
                        credit_note_id=note.id,
                    )
                )

    candidates.sort(key=lambda c: (c.invoice_id, c.match_type))
    return candidates
