import { Routes, Route, Link } from "react-router-dom";
import PaymentList from "./pages/PaymentList";
import PaymentDetail from "./pages/PaymentDetail";

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
          <Route path="/" element={<PaymentList />} />
          <Route path="/payments/:id" element={<PaymentDetail />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </div>
  );
}

function NotFound() {
  return (
    <div className="space-y-3">
      <h1 className="text-3xl">Not found</h1>
      <p className="text-sm text-ink/80">
        No screen for this address.{" "}
        <Link to="/" className="underline">
          Back to payments
        </Link>
        .
      </p>
    </div>
  );
}
