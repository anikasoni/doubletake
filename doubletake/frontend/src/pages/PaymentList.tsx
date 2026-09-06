import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getPayments } from "../api";
import { money } from "../format";
import type { Payment, PaymentStatus } from "../types";

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

export default function PaymentList() {
  const navigate = useNavigate();
  const [payments, setPayments] = useState<Payment[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPayments()
      .then(setPayments)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      );
  }, []);

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h1 className="text-3xl">Payments</h1>
        <p className="max-w-prose text-sm leading-relaxed text-ink/80">
          Every payment received from a customer, and whether it has been matched
          to an invoice yet. Open one to see how the match was decided.
        </p>
      </section>

      {error && <p className="text-sm text-signal-alert">{error}</p>}
      {!error && payments === null && (
        <p className="text-sm text-ink/60">Loading…</p>
      )}

      {payments && (
        <table className="worksheet">
          <thead>
            <tr>
              <th className="w-1/5">Payment ID</th>
              <th className="w-1/5">Customer</th>
              <th className="w-1/5 text-right">Amount</th>
              <th className="w-1/5">Status</th>
            </tr>
          </thead>
          <tbody>
            {payments.map((p) => (
              <tr
                key={p.id}
                onClick={() => navigate(`/payments/${p.id}`)}
                className="cursor-pointer hover:bg-paper-raised"
              >
                <td>
                  <Link
                    to={`/payments/${p.id}`}
                    className="underline"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {p.id}
                  </Link>
                </td>
                <td>{p.customer_id}</td>
                <td className="amount">{money(p.amount)}</td>
                <td className={STATUS_CLASS[p.status]}>
                  {STATUS_TEXT[p.status]}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {payments && payments.length === 0 && (
        <p className="text-sm text-ink/60">
          No payments in the ledger. Seed the demo database and reload.
        </p>
      )}
    </div>
  );
}
