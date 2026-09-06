import { Routes, Route, Link } from "react-router-dom";

/**
 * Scaffolding only. Real screens (payment list, payment worksheet) will be
 * built on top of this once the design tokens are signed off. For now the
 * index route renders a token proof sheet and every other path falls back
 * to it.
 */
export default function App() {
  return (
    <div className="min-h-screen bg-paper text-ink">
      <header className="border-b border-rule">
        <div className="mx-auto max-w-4xl px-6 py-4">
          <Link to="/" className="font-serif text-lg text-ink">
            doubletake
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-6 py-10">
        <Routes>
          <Route path="/" element={<TokenProof />} />
          <Route path="*" element={<TokenProof />} />
        </Routes>
      </main>
    </div>
  );
}

function TokenProof() {
  return (
    <div className="space-y-10">
      <section className="space-y-3">
        <h1 className="text-3xl">Design token proof sheet</h1>
        <p className="max-w-prose text-sm leading-relaxed text-ink/80">
          This page exists to verify the design system before any real screens
          are built. It renders a serif heading, this sans-serif body
          paragraph, a worksheet-style table with a persistent row state in
          each of the three signal colours, and a single hairline-bordered
          panel. Nothing here is wired to the backend yet.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl">Payment comparison worksheet</h2>
        <table className="worksheet">
          <thead>
            <tr>
              <th className="w-1/4">Candidate</th>
              <th className="w-1/4">Amount check</th>
              <th className="w-1/3">Evidence</th>
              <th className="w-1/6">Status</th>
            </tr>
          </thead>
          <tbody>
            <tr className="row-accepted">
              <td>INV-101</td>
              <td className="amount">50,000.00</td>
              <td>Remittance advice references INV-101; amount matches exactly.</td>
              <td className="text-signal-resolved">Accepted</td>
            </tr>
            <tr className="row-rejected">
              <td>INV-202</td>
              <td className="amount">102,000.00</td>
              <td>
                Claimed credit note CN-301 was already consumed by INV-999 —
                ledger contradiction.
              </td>
              <td className="text-signal-alert">Rejected</td>
            </tr>
            <tr className="row-pending">
              <td>INV-402</td>
              <td className="amount">100,000.00</td>
              <td>Payment plus credit note CN-401 balances, but so does INV-401.</td>
              <td className="text-signal-pending">Awaiting review</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl">Bordered panel</h2>
        <div className="panel p-4">
          <h3 className="text-base">Panel heading</h3>
          <p className="mt-1 text-sm text-ink/80">
            Panels use a 1px rule-coloured hairline border on a paper-raised
            background — no drop shadow, minimal corner radius.
          </p>
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
            <dt className="text-ink/60">Payment</dt>
            <dd className="tnum text-right">PAY-201</dd>
            <dt className="text-ink/60">Amount received</dt>
            <dd className="tnum text-right">100,000.00</dd>
            <dt className="text-ink/60">Status</dt>
            <dd className="text-right text-signal-pending">Under review</dd>
          </dl>
        </div>
      </section>
    </div>
  );
}
