"""Offline evaluation harness for the payment-allocation workflow.

Loads every labelled customer in ``data/seed_cases/case_001.json`` and
``data/seed_cases/case_002.json`` (12 customers total) into a throwaway
in-memory SQLite database, runs :func:`app.workflow.process_payment` for every
payment, and scores the actual outcome against the label carried by each case.

The only network call the workflow makes -- the single Anthropic request the
investigator uses to phrase its rationale -- is monkeypatched with a fixed
string, so this script runs with no API key and no live traffic.

Usage (from the project root)::

    python -m scripts.run_eval

Outputs:

* a metrics summary printed to stdout, and
* a per-customer results table written to ``data/eval_results.csv``.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

# Make ``app`` importable when run directly (python scripts/run_eval.py).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.investigator as investigator  # noqa: E402
from app import models  # noqa: E402
from app.db import Base  # noqa: E402
from app.workflow import process_payment  # noqa: E402

SEED_DIR = PROJECT_ROOT / "data" / "seed_cases"
CASE_001 = SEED_DIR / "case_001.json"
CASE_002 = SEED_DIR / "case_002.json"
RESULTS_CSV = PROJECT_ROOT / "data" / "eval_results.csv"

STUB_RATIONALE = "Deterministic outcome; rationale placeholder (eval stub)."

DATE_FIELDS = {"issued_date", "received_date"}

SECTIONS = [
    ("invoices", models.Invoice),
    ("credit_notes", models.CreditNote),
    ("payments", models.Payment),
    ("remittance_advices", models.RemittanceAdvice),
]

# ``case_001.json`` predates the ``expected_*`` labels, so its four customers are
# labelled here from the documented behaviour in tests/test_workflow.py.
CASE_001_EXPECTATIONS = {
    "CUST-01": {
        "expected_outcome": "resolved",
        "expected_selected_invoice_id": "INV-101",
        "expected_contradiction_found": False,
    },
    "CUST-02": {
        "expected_outcome": "resolved",
        "expected_selected_invoice_id": "INV-202",
        "expected_contradiction_found": False,
    },
    "CUST-03": {
        "expected_outcome": "escalate",
        "expected_selected_invoice_id": None,
        "expected_contradiction_found": True,
    },
    "CUST-04": {
        "expected_outcome": "escalate",
        "expected_selected_invoice_id": None,
        "expected_contradiction_found": False,
    },
}


class _FakeMessages:
    def create(self, **kwargs):
        block = SimpleNamespace(type="text", text=STUB_RATIONALE)
        return SimpleNamespace(content=[block])


class _FakeAnthropic:
    def __init__(self, *args, **kwargs):
        self.messages = _FakeMessages()


def _coerce(row: dict) -> dict:
    return {
        key: (date.fromisoformat(value) if key in DATE_FIELDS and isinstance(value, str) else value)
        for key, value in row.items()
    }


def _load_cases() -> tuple[dict[str, list], list[tuple[str, str]], dict[str, dict]]:
    """Return (rows_by_section, [(customer_id, payment_id)], expectations).

    ``case_001.json`` is flat (top-level ``invoices``/``payments``/...), while
    ``case_002.json`` groups rows under per-customer blocks that also carry the
    ``expected_*`` labels. Both are flattened into the same section lists.
    """
    rows_by_section: dict[str, list] = {name: [] for name, _ in SECTIONS}
    order: list[tuple[str, str]] = []
    expectations: dict[str, dict] = {}

    # --- case_001.json: flat structure, labels from the constant above -----
    case_001 = json.loads(CASE_001.read_text(encoding="utf-8"))
    for name, _ in SECTIONS:
        rows_by_section[name].extend(case_001.get(name, []))
    for payment in case_001.get("payments", []):
        cid = payment["customer_id"]
        order.append((cid, payment["id"]))
        expectations[cid] = CASE_001_EXPECTATIONS[cid]

    # --- case_002.json: per-customer blocks carrying their own labels ------
    case_002 = json.loads(CASE_002.read_text(encoding="utf-8"))
    for block in case_002["customers"]:
        cid = block["customer_id"]
        expectations[cid] = {
            "expected_outcome": block["expected_outcome"],
            "expected_selected_invoice_id": block["expected_selected_invoice_id"],
            "expected_contradiction_found": bool(
                block.get("expected_contradiction_found", False)
            ),
        }
        for name, _ in SECTIONS:
            rows_by_section[name].extend(block.get(name, []))
        for payment in block.get("payments", []):
            order.append((cid, payment["id"]))

    return rows_by_section, order, expectations


def _build_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _actual_from_summary(summary: dict) -> dict:
    outcome = "resolved" if summary["outcome"] == "allocated" else "escalate"
    investigation = summary.get("investigation") or {}
    return {
        "actual_outcome": outcome,
        "actual_selected_invoice_id": summary.get("selected_invoice_id"),
        "actual_contradiction_found": bool(
            investigation.get("contradiction_found", False)
        ),
    }


def _pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a (0 cases)"
    return f"{numerator / denominator:.3f}  ({numerator}/{denominator})"


def run_eval() -> dict:
    investigator.anthropic.Anthropic = _FakeAnthropic

    rows_by_section, order, expectations = _load_cases()
    session = _build_session()
    try:
        for name, model in SECTIONS:
            for row in rows_by_section[name]:
                session.add(model(**_coerce(row)))
        session.commit()

        results = []
        for customer_id, payment_id in order:
            summary = process_payment(payment_id, session)
            exp = expectations[customer_id]
            act = _actual_from_summary(summary)

            correct = (
                act["actual_outcome"] == exp["expected_outcome"]
                and act["actual_selected_invoice_id"]
                == exp["expected_selected_invoice_id"]
            )
            results.append(
                {
                    "customer_id": customer_id,
                    "payment_id": payment_id,
                    "expected_outcome": exp["expected_outcome"],
                    "actual_outcome": act["actual_outcome"],
                    "expected_selected_invoice_id": exp["expected_selected_invoice_id"],
                    "actual_selected_invoice_id": act["actual_selected_invoice_id"],
                    "expected_contradiction_found": exp["expected_contradiction_found"],
                    "actual_contradiction_found": act["actual_contradiction_found"],
                    "correct": correct,
                }
            )
    finally:
        session.close()

    _write_csv(results)
    metrics = _score(results)
    _print_summary(results, metrics)
    return {"results": results, "metrics": metrics}


def _write_csv(results: list[dict]) -> None:
    fieldnames = [
        "customer_id",
        "payment_id",
        "expected_outcome",
        "actual_outcome",
        "expected_selected_invoice_id",
        "actual_selected_invoice_id",
        "expected_contradiction_found",
        "actual_contradiction_found",
        "correct",
    ]
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_CSV, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow(row)


def _score(results: list[dict]) -> dict:
    total_count = len(results)

    resolved = [r for r in results if r["actual_outcome"] == "resolved"]
    resolved_count = len(resolved)
    correct_resolved_count = sum(
        1
        for r in resolved
        if r["expected_outcome"] == "resolved"
        and r["actual_selected_invoice_id"] == r["expected_selected_invoice_id"]
    )

    expected_escalate = [r for r in results if r["expected_outcome"] == "escalate"]
    expected_escalate_count = len(expected_escalate)
    correctly_escalated_count = sum(
        1 for r in expected_escalate if r["actual_outcome"] == "escalate"
    )

    expected_contradictions_rows = [
        r for r in results if r["expected_contradiction_found"]
    ]
    expected_contradictions = len(expected_contradictions_rows)
    correctly_flagged_contradictions = sum(
        1
        for r in expected_contradictions_rows
        if r["actual_contradiction_found"] and r["actual_outcome"] == "escalate"
    )

    return {
        "total_count": total_count,
        "resolved_count": resolved_count,
        "correct_resolved_count": correct_resolved_count,
        "expected_escalate_count": expected_escalate_count,
        "correctly_escalated_count": correctly_escalated_count,
        "expected_contradictions": expected_contradictions,
        "correctly_flagged_contradictions": correctly_flagged_contradictions,
        "automatic_resolution_coverage": (
            resolved_count / total_count if total_count else 0.0
        ),
        "automatic_allocation_precision": (
            correct_resolved_count / resolved_count if resolved_count else 0.0
        ),
        "escalation_correctness": (
            correctly_escalated_count / expected_escalate_count
            if expected_escalate_count
            else 0.0
        ),
        "contradiction_catch_rate": (
            correctly_flagged_contradictions / expected_contradictions
            if expected_contradictions
            else 0.0
        ),
    }


def _print_summary(results: list[dict], metrics: dict) -> None:
    n_correct = sum(1 for r in results if r["correct"])
    print("=" * 68)
    print("doubletake payment-allocation eval")
    print("=" * 68)
    print(f"customers evaluated            : {metrics['total_count']}")
    print(f"row-level correct (outcome+inv): {n_correct}/{metrics['total_count']}")
    print("-" * 68)
    print(
        "automatic_resolution_coverage : "
        + _pct(metrics["resolved_count"], metrics["total_count"])
    )
    print(
        "automatic_allocation_precision: "
        + _pct(metrics["correct_resolved_count"], metrics["resolved_count"])
    )
    print(
        "escalation_correctness        : "
        + _pct(
            metrics["correctly_escalated_count"],
            metrics["expected_escalate_count"],
        )
    )
    print(
        "contradiction_catch_rate      : "
        + _pct(
            metrics["correctly_flagged_contradictions"],
            metrics["expected_contradictions"],
        )
    )
    print("-" * 68)
    print(f"results table -> {RESULTS_CSV}")
    print("=" * 68)
    header = f"{'customer':<10} {'expected':<10} {'actual':<10} {'sel(exp/act)':<24} correct"
    print(header)
    print("-" * 68)
    for r in results:
        sel = f"{r['expected_selected_invoice_id']}/{r['actual_selected_invoice_id']}"
        print(
            f"{r['customer_id']:<10} {r['expected_outcome']:<10} "
            f"{r['actual_outcome']:<10} {sel:<24} {r['correct']}"
        )


if __name__ == "__main__":
    run_eval()
