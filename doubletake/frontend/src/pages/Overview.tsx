import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getPayments } from "../api";
import { money } from "../format";
import type { Payment, PaymentStatus } from "../types";

// Copy on this page is lifted from README.md (The problem / Architecture / Demo
// scenarios) rather than written fresh — the landing page should say exactly
// what the project claims about itself.

type Step = { label: string; body: string };

const STEPS: Step[] = [
  {
    label: "Candidate generator",
    body: "Pure arithmetic: given the payment and the customer's open invoices and credit notes, it enumerates every link that balances to the exact payment amount — the invoice alone, or the invoice minus a linked credit note.",
  },
  {
    label: "Investigator",
    body: "Runs only when more than one candidate balances; it gathers evidence in a fixed order — remittance advice first, credit note status second — and records each lookup in an evidence trail.",
  },
  {
    label: "Validator logic",
    body: "From that evidence, plain conditionals decide the outcome: resolve to a specific invoice, or escalate — and the cases backed by a proven ledger conflict set a contradiction flag.",
  },
  {
    label: "Workflow service",
    body: "The glue: zero candidates opens a review case, one candidate is applied directly, and more than one calls the investigator, then applies the selected candidate or opens a review case.",
  },
  {
    label: "Persistence",
    body: "Allocations and review cases are stored with their evidence and rationale, and GET /payments/{id} reconstructs the full worksheet from those rows, so a page reload shows exactly what the run produced.",
  },
];

type Scenario = { paymentId: string; customerId: string; body: string };

const SCENARIOS: Scenario[] = [
  {
    paymentId: "PAY-101",
    customerId: "CUST-01",
    body: "One invoice balances the payment exactly. Single candidate, applied directly, no investigation. Proves the clean path.",
  },
  {
    paymentId: "PAY-201",
    customerId: "CUST-02",
    body: "Two invoices could balance (one exactly, one after a credit note). The remittance names the credit-note candidate and that credit note is still available. Investigation resolves and applies it. Proves that a genuine ambiguity can be settled from evidence.",
  },
  {
    paymentId: "PAY-301",
    customerId: "CUST-03",
    body: "Same shape as CUST-02, but the cited credit note was already consumed by another invoice. Investigation escalates with a contradiction. Proves that a perfect amount match is refused when the evidence contradicts it.",
  },
  {
    paymentId: "PAY-401",
    customerId: "CUST-04",
    body: "Two candidates and no remittance advice on file. The customer's intent cannot be confirmed, so it escalates without a contradiction. Proves that missing evidence escalates rather than guesses.",
  },
];

const STATUS_TEXT: Record<PaymentStatus, string> = {
  allocated: "Allocated",
  under_review: "Under review",
  unallocated: "Unallocated",
};

const STATUS_CLASS: Record<PaymentStatus, string> = {
  allocated: "text-signal-resolved",
  under_review: "text-signal-pending",
  unallocated: "text-ink/60",
};

/** The INV-201 / INV-202 ambiguity as a static, illustrative worksheet. Both
 *  rows mount pending and, once after load, flip to their resolved state — a
 *  single orchestrated CSS transition (see `.landing-demo` in index.css). */
function HeroIllustration() {
  const [resolved, setResolved] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() =>
      requestAnimationFrame(() => setResolved(true)),
    );
    return () => cancelAnimationFrame(raf);
  }, []);

  const rows = [
    {
      invoice: "INV-201",
      check: "Equals the invoice total",
      resolvedClass: "row-rejected",
      resolvedStatus: { text: "Rejected", className: "text-signal-alert" },
    },
    {
      invoice: "INV-202",
      check: "Invoice total less credit note CN-201",
      resolvedClass: "row-accepted",
      resolvedStatus: { text: "Applied", className: "text-signal-resolved" },
    },
  ];

  return (
    <figure className="panel landing-demo p-4 sm:p-5">
      <table className="worksheet">
        <thead>
          <tr>
            <th className="w-1/4">Candidate invoice</th>
            <th className="w-1/2">Amount check</th>
            <th className="w-1/4">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const status = resolved
              ? r.resolvedStatus
              : { text: "Pending", className: "text-signal-pending" };
            return (
              <tr
                key={r.invoice}
                className={resolved ? r.resolvedClass : "row-pending"}
              >
                <td className="tnum">{r.invoice}</td>
                <td>{r.check}</td>
                <td className={status.className}>{status.text}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <figcaption className="mt-3 space-y-1 text-xs leading-relaxed text-ink/60">
        <p>Illustrative example — see live cases below.</p>
        <p>
          The same amount balances two invoices — one exactly, one after
          subtracting credit note CN-201. The remittance advice and credit-note
          status decide which invoice to close.
        </p>
      </figcaption>
    </figure>
  );
}

export default function Overview() {
  const [payments, setPayments] = useState<Payment[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPayments()
      .then(setPayments)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      );
  }, []);

  const byId = new Map((payments ?? []).map((p) => [p.id, p]));

  return (
    <div className="space-y-16">
      {/* HERO */}
      <section className="space-y-5">
        <h1 className="max-w-3xl text-4xl leading-tight sm:text-5xl">
          This payment matches perfectly — and closing it would still be wrong.
        </h1>
        <p className="max-w-prose text-base leading-relaxed text-ink/80">
          An exact amount match is not evidence of intent: doubletake takes one
          incoming payment at a time, enumerates every way it could balance,
          checks the surrounding evidence — remittance advice, credit note
          status — and then either allocates the payment or sends it for human
          review, recording in both cases why.
        </p>
        <HeroIllustration />
      </section>

      {/* HOW IT DECIDES */}
      <section className="space-y-5">
        <h2 className="text-2xl">How it decides</h2>
        <p className="max-w-prose text-sm leading-relaxed text-ink/70">
          A payment moves through five stages. Every stage except the rationale
          sentence is plain, deterministic Python.
        </p>
        <ol className="flex flex-col md:flex-row">
          {STEPS.map((s, i) => (
            <li
              key={s.label}
              className="flex-1 border-t border-rule pt-3 md:border-l md:border-t-0 md:px-4 md:pt-0 md:first:border-l-0 md:first:pl-0"
            >
              <div className="font-serif text-2xl text-ink/40">{i + 1}</div>
              <div className="mt-1 text-sm font-medium text-ink">{s.label}</div>
              <p className="mt-1 text-sm leading-relaxed text-ink/70">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* SEE IT WORK */}
      <section className="space-y-5">
        <h2 className="text-2xl">See it work</h2>
        <p className="max-w-prose text-sm leading-relaxed text-ink/70">
          <code>POST /seed</code> loads four customers, each exercising one path.
        </p>
        {payments === null && !error && (
          <p className="text-sm text-ink/60">Loading live payment data…</p>
        )}
        {error && (
          <p className="text-sm text-signal-alert">
            Could not load live payment data ({error}). Amounts and status are
            hidden below; the links still work.
          </p>
        )}
        <ul className="border-t border-rule">
          {SCENARIOS.map((sc) => {
            const p = byId.get(sc.paymentId);
            return (
              <li
                key={sc.paymentId}
                className="space-y-1 border-b border-rule py-4"
              >
                <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                  <Link
                    to={`/payments/${sc.paymentId}`}
                    className="font-serif text-lg tnum underline"
                  >
                    {sc.paymentId}
                  </Link>
                  <span className="text-sm text-ink/60">{sc.customerId}</span>
                  {p && (
                    <span className="tnum text-sm text-ink/80">
                      {money(p.amount)}
                    </span>
                  )}
                  {p && (
                    <span className={`text-sm ${STATUS_CLASS[p.status]}`}>
                      {STATUS_TEXT[p.status]}
                    </span>
                  )}
                  {!p && payments !== null && !error && (
                    <span className="text-sm text-ink/40">not in ledger</span>
                  )}
                </div>
                <p className="max-w-prose text-sm leading-relaxed text-ink/70">
                  {sc.body}
                </p>
              </li>
            );
          })}
        </ul>
        <p className="text-sm text-ink/60">
          <Link to="/payments" className="underline">
            See all payments
          </Link>
        </p>
      </section>

      {/* CLOSING STATEMENT */}
      <section>
        <div className="panel space-y-3 p-5">
          <h2 className="text-xl">Auditability</h2>
          <p className="max-w-prose text-sm leading-relaxed text-ink/80">
            All allocation decisions are deterministic Python. Every outcome is
            reproducible from the ledger data and the rules alone; the evidence
            trail records what was checked and in what order; the rule that fired
            is stored as the review reason.
          </p>
          <p className="max-w-prose text-sm leading-relaxed text-ink/80">
            The only model call is a single Gemini request at the end of an
            investigation: it is handed the candidates, the evidence trail and
            the outcome the rules already reached, and it returns one or two
            sentences of rationale. It does not choose the invoice, decide
            resolve-versus-escalate, or set the contradiction flag — the model
            sentence is narration over a decision that already stands on its own.
          </p>
        </div>
      </section>
    </div>
  );
}
