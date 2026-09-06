// Small display helpers. The backend serialises Decimal amounts as strings like
// "100000.00" and dates as ISO "2026-02-02"; these turn them into the ledger
// house style (grouped thousands, two decimals; day-month-year date).

export function money(amount: string): string {
  const n = Number(amount);
  if (!Number.isFinite(n)) return amount;
  return n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function isoDate(value: string): string {
  const d = new Date(`${value}T00:00:00`);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}
