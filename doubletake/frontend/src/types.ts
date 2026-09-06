// TypeScript types mirroring app/schemas.py (and the enums in app/models.py).
// Decimal / date / datetime fields are serialised by FastAPI as strings.

export type InvoiceStatus = "open" | "paid" | "partially_paid";
export type CreditNoteStatus = "available" | "consumed";
export type PaymentStatus = "unallocated" | "allocated" | "under_review";
export type AllocationStatus = "applied" | "proposed";
export type ReviewCaseStatus = "pending" | "resolved";

export interface Invoice {
  id: string;
  customer_id: string;
  amount: string; // Decimal
  status: InvoiceStatus;
  issued_date: string; // ISO date
}

export interface CreditNote {
  id: string;
  customer_id: string;
  amount: string; // Decimal
  linked_invoice_id: string | null;
  status: CreditNoteStatus;
  consumed_by_invoice_id: string | null;
}

export interface Payment {
  id: string;
  customer_id: string;
  amount: string; // Decimal
  received_date: string; // ISO date
  status: PaymentStatus;
}

export interface RemittanceAdvice {
  id: string;
  payment_id: string;
  referenced_invoice_id: string | null;
  referenced_credit_note_id: string | null;
  raw_text: string;
}

export interface Allocation {
  id: string;
  payment_id: string;
  invoice_id: string;
  amount: string; // Decimal
  status: AllocationStatus;
  evidence_used: unknown[];
  created_at: string; // ISO datetime
  decision_rationale: string;
}

export interface ReviewCase {
  id: string;
  payment_id: string;
  competing_candidates: CompetingCandidate[];
  reason: string;
  decision_rationale: string;
  contradiction_found: boolean;
  status: ReviewCaseStatus;
  created_at: string; // ISO datetime
}

// Shape stored in ReviewCase.competing_candidates and returned in
// ProcessResult.competing_candidates by app/workflow.py.
export type MatchType = "exact_amount" | "invoice_minus_credit_note";

export interface CompetingCandidate {
  invoice_id: string;
  match_type: MatchType | string;
  credit_note_id: string | null;
}

// One entry appended to InvestigationSummary.evidence_checked by
// app/investigator.py. Which keys are present depends on evidence_type and what
// the check found, so everything past evidence_type is optional.
export interface EvidenceEntry {
  evidence_type: "remittance_advice" | "credit_note_status" | string;
  found?: boolean;
  detail?: string;
  referenced_invoice_id?: string | null;
  referenced_credit_note_id?: string | null;
  credit_note_id?: string | null;
  status?: string | null;
  consumed_by_invoice_id?: string | null;
}

// Return shape of POST /payments/{id}/process (app/workflow.process_payment).
export type ProcessPath = "no_candidates" | "single_candidate" | "investigated";
export type ProcessOutcome = "allocated" | "under_review";

export interface InvestigationSummary {
  status: "resolved" | "escalate";
  selected_invoice_id: string | null;
  contradiction_found: boolean;
  decision_rationale: string;
  evidence_checked: EvidenceEntry[];
}

export interface ProcessResult {
  payment_id: string;
  path: ProcessPath;
  outcome: ProcessOutcome;
  candidate_count: number;
  selected_invoice_id: string | null;
  allocation_id: string | null;
  review_case_id: string | null;
  review_reason?: string;
  competing_candidates: CompetingCandidate[];
  investigation: InvestigationSummary | null;
}

// Return shape of GET /payments/{id} (app/schemas.PaymentDetailSchema). Carries
// the base payment plus, once processed, the full investigation detail needed
// to rebuild the worksheet / evidence trail / outcome banner with no
// re-processing. `allocation` is set iff it resolved; `review_case` iff it
// escalated; both null while `status` is "unallocated".
export interface PaymentAllocation {
  invoice_id: string;
  amount: string; // Decimal
  evidence_used: EvidenceEntry[];
  decision_rationale: string;
}

export interface PaymentReviewCase {
  competing_candidates: CompetingCandidate[];
  decision_rationale: string;
  contradiction_found: boolean;
  evidence_checked: EvidenceEntry[];
  status: ReviewCaseStatus;
}

export interface PaymentDetail {
  id: string;
  customer_id: string;
  amount: string; // Decimal
  received_date: string; // ISO date
  status: PaymentStatus;
  candidates: CompetingCandidate[];
  allocation: PaymentAllocation | null;
  review_case: PaymentReviewCase | null;
}
