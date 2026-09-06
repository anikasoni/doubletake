"""Deterministic investigation of ambiguous payment allocations.

When :func:`app.candidates.generate_candidates` returns more than one balancing
candidate for a payment, the allocation is ambiguous and has to be investigated
before it can be applied.  This module runs that investigation.

**Every decision here is deterministic.**  Which invoice (if any) is selected,
whether the case resolves or escalates, and whether a contradiction was found are
all decided by plain Python from ledger evidence.  The Anthropic API is called
exactly once, at the very end, and only to phrase ``decision_rationale`` in
English -- it is given the already-made outcome and must not change it.

Investigation should only be run when ``len(candidates) > 1``; a single candidate
is unambiguous and :func:`investigate` rejects that input.
"""

from __future__ import annotations

import json
from typing import Literal

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

from app.candidates import Candidate
from app.models import CreditNote, RemittanceAdvice

# Load ANTHROPIC_API_KEY (and anything else in .env) on import.
load_dotenv()

RATIONALE_MODEL = "claude-sonnet-4-6"

# The rationale writer summarises supplied facts only.  It never decides the
# outcome and must not invent identifiers or amounts.
_RATIONALE_SYSTEM = (
    "You write a short, factual rationale for an accounts-receivable payment "
    "allocation decision that has ALREADY been made by deterministic rules. You "
    "do not make, confirm, or change the decision. Using ONLY the facts given in "
    "the user message, write 1 to 2 plain-text sentences explaining why that "
    "outcome was reached. Never introduce invoice IDs, credit note IDs, payment "
    "IDs, or amounts that are not present in the input. Do not speculate and do "
    "not add recommendations. Return plain text only -- no markdown, no preamble."
)


class InvestigationResult(BaseModel):
    """Outcome of investigating one ambiguous payment allocation."""

    status: Literal["resolved", "escalate"]
    selected_invoice_id: str | None
    decision_rationale: str
    evidence_checked: list[dict]
    contradiction_found: bool


def _status_value(status) -> str:
    """Return the plain string value of an enum-or-string status field."""
    return getattr(status, "value", status)


def fetch_remittance_advice(payment_id, db_session) -> RemittanceAdvice | None:
    """Return the remittance advice row for ``payment_id``, or ``None``."""
    return (
        db_session.query(RemittanceAdvice)
        .filter(RemittanceAdvice.payment_id == payment_id)
        .first()
    )


def check_credit_note_status(credit_note_id, db_session) -> dict:
    """Look up a credit note and report whether it is still usable.

    Returns a dict with ``id``, ``status`` and ``consumed_by_invoice_id``.  If
    the credit note does not exist, ``status`` and ``consumed_by_invoice_id`` are
    ``None``.
    """
    note = (
        db_session.query(CreditNote)
        .filter(CreditNote.id == credit_note_id)
        .first()
    )
    if note is None:
        return {
            "id": credit_note_id,
            "status": None,
            "consumed_by_invoice_id": None,
        }
    return {
        "id": note.id,
        "status": _status_value(note.status),
        "consumed_by_invoice_id": note.consumed_by_invoice_id,
    }


def rank_evidence_options(candidates: list[Candidate]) -> list[dict]:
    """Return the fixed, deterministic order in which to gather evidence.

    No LLM ranking -- the order is always remittance advice first (it says which
    invoice the customer meant), then credit note status (it says whether a
    claimed credit is still valid).
    """
    return [
        {
            "evidence_type": "remittance_advice",
            "reason": (
                "would directly indicate which invoice the customer intended "
                "to pay"
            ),
        },
        {
            "evidence_type": "credit_note_status",
            "reason": "would confirm whether the claimed credit is still valid",
        },
    ]


def _candidate_dict(candidate: Candidate) -> dict:
    return {
        "invoice_id": candidate.invoice_id,
        "match_type": candidate.match_type,
        "credit_note_id": candidate.credit_note_id,
    }


def generate_rationale(
    payment,
    candidates: list[Candidate],
    evidence_checked: list[dict],
    outcome: dict,
) -> str:
    """Make the single Anthropic call that phrases ``decision_rationale``.

    The model is handed the candidates, the evidence gathered and the outcome
    that deterministic logic already reached; it only turns those facts into a
    sentence or two.
    """
    client = anthropic.Anthropic()
    facts = {
        "payment_id": getattr(payment, "id", None),
        "candidates": [_candidate_dict(c) for c in candidates],
        "evidence_checked": evidence_checked,
        "outcome": outcome,
    }
    response = client.messages.create(
        model=RATIONALE_MODEL,
        max_tokens=300,
        system=_RATIONALE_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    "Facts (JSON):\n"
                    + json.dumps(facts, indent=2, sort_keys=True, default=str)
                    + "\n\nWrite the rationale."
                ),
            }
        ],
    )
    return "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()


def _finish(
    payment,
    candidates: list[Candidate],
    evidence_checked: list[dict],
    outcome: dict,
) -> InvestigationResult:
    """Attach an LLM-written rationale and build the result object."""
    rationale = generate_rationale(payment, candidates, evidence_checked, outcome)
    return InvestigationResult(
        status=outcome["status"],
        selected_invoice_id=outcome["selected_invoice_id"],
        decision_rationale=rationale,
        evidence_checked=evidence_checked,
        contradiction_found=outcome["contradiction_found"],
    )


def investigate(
    payment,
    candidates: list[Candidate],
    db_session,
) -> InvestigationResult:
    """Investigate an ambiguous allocation and resolve or escalate it.

    Args:
        payment: object with an ``id`` attribute.
        candidates: the balancing candidates from
            :func:`app.candidates.generate_candidates`; must contain more than
            one entry.
        db_session: a SQLAlchemy session for evidence lookups.
    """
    if len(candidates) <= 1:
        raise ValueError(
            "investigate() requires more than one candidate; a single candidate "
            "is unambiguous and needs no investigation"
        )

    # Deterministic fetch order: remittance advice first, credit note second.
    fetch_order = rank_evidence_options(candidates)
    assert fetch_order[0]["evidence_type"] == "remittance_advice"

    evidence_checked: list[dict] = []

    remittance = fetch_remittance_advice(payment.id, db_session)

    # --- Missing remittance advice -----------------------------------------
    if remittance is None:
        evidence_checked.append(
            {
                "evidence_type": "remittance_advice",
                "found": False,
                "detail": (
                    f"no remittance advice on file for payment {payment.id}"
                ),
            }
        )
        outcome = {
            "status": "escalate",
            "selected_invoice_id": None,
            "contradiction_found": False,
            "reason": "missing_remittance_advice",
        }
        return _finish(payment, candidates, evidence_checked, outcome)

    evidence_checked.append(
        {
            "evidence_type": "remittance_advice",
            "found": True,
            "referenced_invoice_id": remittance.referenced_invoice_id,
            "referenced_credit_note_id": remittance.referenced_credit_note_id,
        }
    )

    # --- Remittance points at an invoice that is not a candidate ----------
    matches = [
        c for c in candidates if c.invoice_id == remittance.referenced_invoice_id
    ]
    if not matches:
        outcome = {
            "status": "escalate",
            "selected_invoice_id": None,
            # The remittance points outside the candidate set, but this is an
            # unresolved conflict rather than a proven contradiction in the
            # ledger, so it does not set contradiction_found.
            "contradiction_found": False,
            "reason": "remittance_references_invoice_with_no_candidate",
        }
        return _finish(payment, candidates, evidence_checked, outcome)

    # Pick the candidate the remittance describes: if it cites a credit note,
    # prefer the deduction candidate carrying that note; otherwise prefer the
    # plain exact-amount match. Falls back to the first match for determinism.
    selected = None
    cited_credit_note_id = remittance.referenced_credit_note_id
    if cited_credit_note_id:
        selected = next(
            (c for c in matches if c.credit_note_id == cited_credit_note_id),
            None,
        )
        if selected is None:
            # The remittance names a specific credit note, but no candidate for
            # the referenced invoice is actually linked to it. If that invoice
            # only balances via a deduction against a *different* credit note,
            # the cited evidence does not support the referenced invoice -- a
            # proven ledger contradiction, not a licence to silently fall back
            # to another candidate.
            deduction_match = next(
                (
                    c
                    for c in matches
                    if c.match_type == "invoice_minus_credit_note"
                ),
                None,
            )
            if deduction_match is not None:
                evidence_checked.append(
                    {
                        "evidence_type": "credit_note_status",
                        "credit_note_id": cited_credit_note_id,
                        "status": None,
                        "consumed_by_invoice_id": None,
                        "detail": (
                            f"remittance cites credit note "
                            f"{cited_credit_note_id}, but candidate invoice "
                            f"{deduction_match.invoice_id} is linked to credit "
                            f"note {deduction_match.credit_note_id}"
                        ),
                    }
                )
                outcome = {
                    "status": "escalate",
                    "selected_invoice_id": None,
                    "contradiction_found": True,
                    "reason": "remittance_credit_note_does_not_match_candidate",
                    "cited_credit_note_id": cited_credit_note_id,
                    "candidate_credit_note_id": deduction_match.credit_note_id,
                }
                return _finish(payment, candidates, evidence_checked, outcome)
    if selected is None:
        selected = next(
            (c for c in matches if c.match_type == "exact_amount"), matches[0]
        )

    # --- Deduction candidate: the claimed credit note must still be valid --
    if selected.match_type == "invoice_minus_credit_note":
        cn_status = check_credit_note_status(selected.credit_note_id, db_session)
        evidence_checked.append(
            {
                "evidence_type": "credit_note_status",
                "credit_note_id": cn_status["id"],
                "status": cn_status["status"],
                "consumed_by_invoice_id": cn_status["consumed_by_invoice_id"],
            }
        )
        if cn_status["status"] == "consumed":
            outcome = {
                "status": "escalate",
                "selected_invoice_id": None,
                "contradiction_found": True,
                "reason": "claimed_credit_note_already_consumed",
                "consumed_by_invoice_id": cn_status["consumed_by_invoice_id"],
            }
        else:
            outcome = {
                "status": "resolved",
                "selected_invoice_id": selected.invoice_id,
                "contradiction_found": False,
                "reason": "remittance_matches_candidate_with_available_credit_note",
            }
        return _finish(payment, candidates, evidence_checked, outcome)

    # --- Exact-amount candidate: resolve directly, no credit check --------
    outcome = {
        "status": "resolved",
        "selected_invoice_id": selected.invoice_id,
        "contradiction_found": False,
        "reason": "remittance_matches_exact_amount_candidate",
    }
    return _finish(payment, candidates, evidence_checked, outcome)
