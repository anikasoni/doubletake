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

// Shape stored in ReviewCase.competing_candidates by app/workflow.py.
export interface CompetingCandidate {
  invoice_id: string;
  match_type: string;
  credit_note_id: string | null;
}

// Return shape of POST /payments/{id}/process (app/workflow.process_payment).
export type ProcessPath = "no_candidates" | "single_candidate" | "investigated";
export type ProcessOutcome = "allocated" | "under_review";

export interface InvestigationSummary {
  status: "resolved" | "escalate";
  selected_invoice_id: string | null;
  contradiction_found: boolean;
  decision_rationale: string;
  evidence_checked: unknown[];
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
  investigation: InvestigationSummary | null;
}
