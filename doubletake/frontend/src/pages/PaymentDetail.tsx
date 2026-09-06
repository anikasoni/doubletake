import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getPayment, processPayment } from "../api";
import { isoDate, money } from "../format";
import type {
  CompetingCandidate,
  EvidenceEntry,
  PaymentDetail as PaymentDetailData,
  ProcessResult,
} from "../types";

type Verdict = "accepted" | "rejected" | "pending";

const VERDICT_ROW: Record<Verdict, string> = {
  accepted: "row-accepted",
  rejected: "row-rejected",
  pending: "row-pending",
};

const VERDICT_STATUS: Record<Verdict, { text: string; className: string }> = {
  accepted: { text: "Applied", className: "text-signal-resolved" },
  rejected: { text: "Rejected", className: "text-signal-alert" },
  pending: { text: "Awaiting review", className: "text-signal-pending" },
};

function matchTypeLabel(matchType: string): string {
  if (matchType === "exact_amount") return "Exact amount match";
  if (matchType === "invoice_minus_credit_note") return "Invoice less credit note";
  return matchType;
}

/** Build the render model the sections below expect from the payment-detail
 *  API response. Returns null while the payment is still unallocated (nothing
 *  to show yet). An allocation means it resolved; a review case means it
 *  escalated. */
function detailToResult(d: PaymentDetailData): ProcessResult | null {
  if (d.status === "unallocated") return null;

  if (d.allocation) {
    const investigated = d.candidates.length > 1;
    return {
      payment_id: d.id,
      path: investigated ? "investigated" : "single_candidate",
      outcome: "allocated",
      candidate_count: d.candidates.length,
      selected_invoice_id: d.allocation.invoice_id,
      allocation_id: null,
      review_case_id: null,
      competing_candidates: d.candidates,
      investigation: investigated
        ? {
            status: "resolved",
            selected_invoice_id: d.allocation.invoice_id,
            contradiction_found: false,
            decision_rationale: d.allocation.decision_rationale,
            evidence_checked: d.allocation.evidence_used,
          }
        : null,
    };
  }

  if (d.review_case) {
    return {
      payment_id: d.id,
      path: "investigated",
      outcome: "under_review",
      candidate_count: d.candidates.length,
      selected_invoice_id: null,
      allocation_id: null,
      review_case_id: null,
      competing_candidates: d.candidates,
      investigation: {
        status: "escalate",
        selected_invoice_id: null,
        contradiction_found: d.review_case.contradiction_found,
        decision_rationale: d.review_case.decision_rationale,
        evidence_checked: d.review_case.evidence_checked,
      },
    };
  }

  return null;
}

/** True when the ledger contradiction the investigation found lands on this
 *  candidate — i.e. a credit-note check that came back consumed or unmatched
 *  for the exact note this candidate depends on. */
function candidateIsContradicted(
  candidate: CompetingCandidate,
  evidence: EvidenceEntry[],
): boolean {
  if (!candidate.credit_note_id) return false;
  return evidence.some(
    (e) =>
      e.evidence_type === "credit_note_status" &&
      e.credit_note_id === candidate.credit_note_id &&
      (e.status === "consumed" || (e.status == null && Boolean(e.detail))),
  );
}

function verdictFor(
  candidate: CompetingCandidate,
  result: ProcessResult,
): Verdict {
  if (result.outcome === "allocated") {
    return candidate.invoice_id === result.selected_invoice_id
      ? "accepted"
      : "rejected";
  }
  const evidence = result.investigation?.evidence_checked ?? [];
  if (
    result.investigation?.contradiction_found &&
    candidateIsContradicted(candidate, evidence)
  ) {
    return "rejected";
  }
  return "pending";
}

function amountCheckText(candidate: CompetingCandidate): string {
  if (candidate.match_type === "invoice_minus_credit_note") {
    return `Invoice total less credit note ${candidate.credit_note_id ?? ""}`.trim();
  }
  return "Equals the invoice total";
}

function evidenceForCandidate(
  candidate: CompetingCandidate,
  evidence: EvidenceEntry[],
): string {
  const lines: string[] = [];
  for (const e of evidence) {
    if (e.evidence_type === "remittance_advice" && e.found) {
      if (e.referenced_invoice_id === candidate.invoice_id) {
        lines.push(
          e.referenced_credit_note_id
            ? `Remittance advice names this invoice and cites credit note ${e.referenced_credit_note_id}`
            : "Remittance advice names this invoice",
        );
      }
    }
    if (
      e.evidence_type === "credit_note_status" &&
      candidate.credit_note_id &&
      e.credit_note_id === candidate.credit_note_id
    ) {
      if (e.status === "consumed") {
        lines.push(
          `Credit note ${e.credit_note_id} already consumed by ${e.consumed_by_invoice_id ?? "another invoice"}`,
        );
      } else if (e.status === "available") {
        lines.push(`Credit note ${e.credit_note_id} still available`);
      } else if (e.detail) {
        lines.push(e.detail);
      } else {
        lines.push(`Credit note ${e.credit_note_id}: ${String(e.status)}`);
      }
    }
  }
  return lines.length > 0 ? lines.join("; ") : "Not referenced by any evidence";
}

function evidenceTrailLine(e: EvidenceEntry): string {
  if (e.evidence_type === "remittance_advice") {
    if (!e.found) {
      return e.detail ?? "Remittance advice — none on file for this payment.";
    }
    const cite = e.referenced_credit_note_id
      ? `, cites credit note ${e.referenced_credit_note_id}`
      : "";
    return `Remittance advice — found, references ${e.referenced_invoice_id ?? "no invoice"}${cite}.`;
  }
  if (e.evidence_type === "credit_note_status") {
    if (e.status === "consumed") {
      return `Credit note ${e.credit_note_id} — already consumed by ${e.consumed_by_invoice_id ?? "another invoice"}, so it cannot cover this payment.`;
    }
    if (e.status === "available") {
      return `Credit note ${e.credit_note_id} — available and valid to apply.`;
    }
    if (e.detail) {
      return `Credit note ${e.credit_note_id} — ${e.detail}.`;
    }
    return `Credit note ${e.credit_note_id} — status ${String(e.status)}.`;
  }
  return JSON.stringify(e);
}

function outcomeBanner(result: ProcessResult): {
  text: string;
  className: string;
} {
  if (result.outcome === "allocated") {
    const others = result.competing_candidates
      .map((c) => c.invoice_id)
      .filter((id) => id !== result.selected_invoice_id);
    let tail = "";
    if (others.length === 1) tail = ` ${others[0]} remains outstanding.`;
    else if (others.length > 1)
      tail = ` ${others.join(", ")} remain outstanding.`;
    return {
      text: `Applied to ${result.selected_invoice_id}.${tail}`,
      className: "text-signal-resolved",
    };
  }
  const rationale =
    result.investigation?.decision_rationale ||
    result.review_reason ||
    "no automatic resolution";
  return {
    text: `Sent for review: ${rationale}`,
    className: result.investigation?.contradiction_found
      ? "text-signal-alert"
      : "text-signal-pending",
  };
}

export default function PaymentDetail() {
  const { id = "" } = useParams();
  const [detail, setDetail] = useState<PaymentDetailData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [processError, setProcessError] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);
  // The candidate rows mount pending and transition to their verdict once a
  // result is in hand (see the `.row-*` transitions in index.css) — so clicking
  // "Process payment" eases into the outcome rather than snapping to it.
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    setDetail(null);
    setLoadError(null);
    setProcessError(null);
    getPayment(id)
      .then(setDetail)
      .catch((err: unknown) =>
        setLoadError(err instanceof Error ? err.message : String(err)),
      );
  }, [id]);

  const result = detail ? detailToResult(detail) : null;
  const hasResult = result !== null;

  useEffect(() => {
    if (!hasResult) {
      setRevealed(false);
      return;
    }
    const raf = requestAnimationFrame(() =>
      requestAnimationFrame(() => setRevealed(true)),
    );
    return () => cancelAnimationFrame(raf);
  }, [hasResult]);

  const runProcess = useCallback(async () => {
    setProcessing(true);
    setProcessError(null);
    try {
      await processPayment(id);
      // Re-fetch through the same endpoint the page loads from, so a reload or
      // a navigate-away-and-back renders exactly what we show now.
      setDetail(await getPayment(id));
    } catch (err: unknown) {
      setProcessError(err instanceof Error ? err.message : String(err));
    } finally {
      setProcessing(false);
    }
  }, [id]);

  if (loadError) {
    return (
      <div className="space-y-4">
        <BackLink />
        <p className="text-sm text-signal-alert">{loadError}</p>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="space-y-4">
        <BackLink />
        <p className="text-sm text-ink/60">Loading…</p>
      </div>
    );
  }

  const investigation = result?.investigation ?? null;

  return (
    <div className="space-y-8">
      <BackLink />

      {/* 1. Header block — the payment amount is the hero. */}
      <div className="panel p-5">
        <div className="text-4xl font-serif tnum">{money(detail.amount)}</div>
        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="text-ink/60">Payment</dt>
          <dd className="tnum">{detail.id}</dd>
          <dt className="text-ink/60">Customer</dt>
          <dd>{detail.customer_id}</dd>
          <dt className="text-ink/60">Received</dt>
          <dd>{isoDate(detail.received_date)}</dd>
        </dl>
      </div>

      {/* 2. Process action — only while the payment is still unallocated. */}
      {detail.status === "unallocated" && (
        <div className="space-y-2">
          <button
            type="button"
            onClick={runProcess}
            disabled={processing}
            className="border border-ink px-4 py-2 text-sm text-ink hover:bg-paper-raised disabled:opacity-50"
          >
            {processing ? "Processing…" : "Process payment"}
          </button>
          {processError && (
            <p className="text-sm text-signal-alert">{processError}</p>
          )}
        </div>
      )}

      {result && (
        <>
          {/* 3. Candidate comparison worksheet. */}
          <section className="space-y-3">
            <h2 className="text-xl">Candidate comparison</h2>
            {result.competing_candidates.length === 0 ? (
              <p className="text-sm text-ink/70">
                No balancing invoice was found for this payment.
              </p>
            ) : (
              <table className="worksheet">
                <thead>
                  <tr>
                    <th className="w-1/6">Candidate invoice</th>
                    <th className="w-1/4">Amount check</th>
                    <th className="w-1/3">Evidence</th>
                    <th className="w-1/6">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {result.competing_candidates.map((c) => {
                    const verdict = revealed
                      ? verdictFor(c, result)
                      : "pending";
                    const status = VERDICT_STATUS[verdict];
                    return (
                      <tr key={c.invoice_id} className={VERDICT_ROW[verdict]}>
                        <td className="tnum">{c.invoice_id}</td>
                        <td>{amountCheckText(c)}</td>
                        <td>
                          {evidenceForCandidate(
                            c,
                            investigation?.evidence_checked ?? [],
                          )}
                        </td>
                        <td className={status.className}>{status.text}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </section>

          {/* 4. Evidence trail — what was checked, in order, and what it found. */}
          <section className="space-y-3">
            <h2 className="text-xl">Evidence trail</h2>
            {investigation ? (
              <>
                <ol className="space-y-1 text-sm text-ink/80">
                  {investigation.evidence_checked.map((e, i) => (
                    <li key={i}>{evidenceTrailLine(e as EvidenceEntry)}</li>
                  ))}
                </ol>
                {investigation.decision_rationale && (
                  <p className="max-w-prose text-sm text-ink">
                    Conclusion — {investigation.decision_rationale}
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-ink/80">
                Only one invoice balanced this payment, so it was applied
                automatically — nothing needed to be investigated.
              </p>
            )}
          </section>

          {/* 5. Outcome banner. */}
          <OutcomeBanner result={result} />

          {/* 6. Review panel — competing candidates, one more look. */}
          {result.outcome === "under_review" &&
            result.competing_candidates.length > 0 && (
              <section className="space-y-3">
                <h2 className="text-xl">For review</h2>
                <div className="grid gap-4 sm:grid-cols-2">
                  {result.competing_candidates.map((c) => (
                    <div key={c.invoice_id} className="panel p-4">
                      <div className="font-serif text-lg tnum">
                        {c.invoice_id}
                      </div>
                      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                        <dt className="text-ink/60">Match</dt>
                        <dd>{matchTypeLabel(c.match_type)}</dd>
                        {c.credit_note_id && (
                          <>
                            <dt className="text-ink/60">Credit note</dt>
                            <dd className="tnum">{c.credit_note_id}</dd>
                          </>
                        )}
                      </dl>
                    </div>
                  ))}
                </div>
                <p className="text-sm text-signal-pending">Awaiting a decision</p>
              </section>
            )}
        </>
      )}
    </div>
  );
}

function OutcomeBanner({ result }: { result: ProcessResult }) {
  const { text, className } = outcomeBanner(result);
  return (
    <div className="panel p-4">
      <p className={`text-sm ${className}`}>{text}</p>
    </div>
  );
}

function BackLink() {
  return (
    <Link to="/payments" className="text-sm text-ink/70 underline">
      ← Payments
    </Link>
  );
}
