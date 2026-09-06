# Doubletake

## The problem

In accounts receivable, a customer payment often matches an open invoice to the
cent — and closing that invoice would still be the wrong call. The same amount
can balance against more than one invoice; it can balance against an invoice only
after subtracting a credit note that was already used up somewhere else; it can
balance against an invoice the customer never named in their remittance advice.
An exact amount match is not evidence of intent. doubletake takes one incoming
payment at a time, enumerates every way it could balance, checks the surrounding
evidence (remittance advice, credit note status), and then either allocates the
payment or sends it for human review — recording, in both cases, why.

## Setup

The repository root holds a `doubletake/` directory; the Python project lives one
level down.

```
git clone https://github.com/anikasoni/doubletake
cd doubletake/doubletake
```

### Backend

Run from `doubletake/doubletake/` (the directory that contains the `app`
package).

```
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file next to `requirements.txt` with a Google Gemini API key.
The key is only used to phrase the decision rationale (see Architecture); the
allocation logic runs without it, but the workflow will error on the Gemini call
if it is missing when an ambiguous payment is processed.

```
GEMINI_API_KEY=your-key-here
```

Get a free key at https://aistudio.google.com/app/apikey — no billing required for the free tier.

Start the API:

```
uvicorn app.main:app --reload
```

It listens on `http://127.0.0.1:8000`; interactive docs are at
`http://127.0.0.1:8000/docs`. The SQLite database is created automatically at
`data/ledger.db`.

### Frontend

Run from `doubletake/doubletake/frontend/`. Needs Node 18+ and the backend
running on port 8000.

```
cd frontend
npm install
npm run dev
```

The dev server runs on `http://localhost:5173`. Requests to `/api/*` are proxied
to the backend.

### Seed demo data

```
curl -X POST http://127.0.0.1:8000/seed
```

`POST /seed` wipes the database and reloads it from
`data/seed_cases/case_001.json` — the four demo scenarios below. The same load is
available from the command line with `python -m scripts.seed_db`.

## Architecture

A payment moves through five stages. Every stage except the rationale sentence is
plain, deterministic Python.

1. **Candidate generator** (`app/candidates.py`, `generate_candidates`). Pure
   arithmetic: given the payment and the customer's open invoices and credit
   notes, it enumerates every link that balances to the exact payment amount —
   either the invoice alone (`exact_amount`) or the invoice minus a linked credit
   note (`invoice_minus_credit_note`). It does no I/O and decides nothing about
   whether a credit note is actually usable.

2. **Investigator** (`app/investigator.py`, `investigate`). Runs only when more
   than one candidate balances. It gathers evidence in a fixed order —
   remittance advice first (which invoice did the customer name?), credit note
   status second (is the cited credit still available?) — and records each lookup
   in an evidence trail.

3. **Validator logic, embedded in `investigate()`**. From that evidence, plain
   conditionals decide the outcome: resolve to a specific invoice, or escalate.
   A remittance that names a candidate invoice and (where relevant) a still
   available credit note resolves. A consumed credit note, a remittance whose
   cited credit note does not match the candidate, a remittance pointing outside
   the candidate set, or no remittance at all escalates — and the cases backed by
   a proven ledger conflict set `contradiction_found`.

4. **Workflow service** (`app/workflow.py`, `process_payment`). The glue.
   Zero candidates opens a review case and parks the payment. One candidate is
   applied directly. More than one candidate calls the investigator, then applies
   the selected candidate or opens a review case carrying the investigation's
   rationale, competing candidates and contradiction flag.

5. **Persistence** (`app/models.py`, `app/db.py`; SQLAlchemy over SQLite).
   Allocations and review cases are written with their evidence and rationale.
   `GET /payments/{id}` reconstructs the full worksheet — evaluated candidates,
   evidence trail, outcome — from stored rows, so a page reload shows exactly
   what the run produced.

**All allocation decisions are deterministic Python.** The only model call is a
single Google Gemini request at the end of an investigation. It is handed the
candidates, the evidence trail and the outcome that the rules already reached,
and it returns one or two sentences of `decision_rationale`. It does not choose
the invoice, decide resolve-versus-escalate, or set the contradiction flag, and
it is instructed not to introduce identifiers or amounts that are not in its
input.

This matters for **auditability**. Every outcome is reproducible from the ledger
data and the rules alone; the evidence trail records what was checked and in what
order; the rule that fired is stored as the review reason. The Gemini sentence is
narration over a decision that already stands on its own — a reviewer can accept
or reject the allocation without having to trust the model.

## Demo scenarios

`POST /seed` loads four customers, each exercising one path:

- **CUST-01 / PAY-101** — one invoice balances the payment exactly. Single
  candidate, applied directly, no investigation. Proves the clean path.
- **CUST-02 / PAY-201** — two invoices could balance (one exactly, one after a
  credit note). The remittance names the credit-note candidate and that credit
  note is still available. Investigation resolves and applies it. Proves that a
  genuine ambiguity can be settled from evidence.
- **CUST-03 / PAY-301** — same shape as CUST-02, but the cited credit note was
  already consumed by another invoice. Investigation escalates with
  `contradiction_found`. Proves that a perfect amount match is refused when the
  evidence contradicts it.
- **CUST-04 / PAY-401** — two candidates and no remittance advice on file. The
  customer's intent cannot be confirmed, so it escalates without a contradiction.
  Proves that missing evidence escalates rather than guesses.

Nine more labeled cases (CUST-05 through CUST-13) live in
`data/seed_cases/case_002.json` for the eval harness — additional clean matches,
resolvable ambiguities, consumed-credit-note contradictions, a missing-remittance
escalation, and a remittance that cites a credit note linked to the wrong
invoice.

## Running the eval

From `doubletake/doubletake/`:

```
python -m scripts.run_eval
```

It loads all 13 labeled customers into an in-memory database, runs
`process_payment` for each, and scores the outcome and selected invoice against
the label. The Gemini call is stubbed, so no API key or network is used. A
per-customer table is written to `data/eval_results.csv`.

Current metrics:

```
====================================================================
doubletake payment-allocation eval
====================================================================
customers evaluated            : 13
row-level correct (outcome+inv): 13/13
--------------------------------------------------------------------
automatic_resolution_coverage : 0.538  (7/13)
automatic_allocation_precision: 1.000  (7/7)
escalation_correctness        : 1.000  (6/6)
contradiction_catch_rate      : 1.000  (4/4)
--------------------------------------------------------------------
results table -> <project>/data/eval_results.csv
====================================================================
customer   expected   actual     sel(exp/act)             correct
--------------------------------------------------------------------
CUST-01    resolved   resolved   INV-101/INV-101          True
CUST-02    resolved   resolved   INV-202/INV-202          True
CUST-03    escalate   escalate   None/None                True
CUST-04    escalate   escalate   None/None                True
CUST-05    resolved   resolved   INV-501/INV-501          True
CUST-06    resolved   resolved   INV-601/INV-601          True
CUST-07    resolved   resolved   INV-701/INV-701          True
CUST-08    resolved   resolved   INV-802/INV-802          True
CUST-09    resolved   resolved   INV-902/INV-902          True
CUST-10    escalate   escalate   None/None                True
CUST-11    escalate   escalate   None/None                True
CUST-12    escalate   escalate   None/None                True
CUST-13    escalate   escalate   None/None                True
```

`automatic_resolution_coverage` is the share of payments the workflow allocated
without review; the other three are accuracy against the labels for the
allocated, escalated, and contradiction cases respectively.

## Known limitations

- **Incoming customer payments only.** The workflow matches money received from a
  customer against that customer's open receivable invoices. Supplier payments,
  outbound transfers and other ledger movements are out of scope.
- **Full settlement is assumed.** A candidate only exists if it balances to the
  exact invoice total — the payment alone, or the payment plus one linked credit
  note — so an applied allocation always closes the invoice. Partial payments,
  under-payments and over-payments are not handled yet; such a payment produces
  no candidate and goes to review.
- **Credit-note-citation matching is exact, not fuzzy.** When a remittance cites
  a specific credit note, the investigator checks that the balancing candidate
  depends on that exact note. If the remittance cites CN-X but the candidate
  balances via CN-Y, that is treated as a contradiction and escalated, not
  reconciled.
- **Gemini rationale phrasing is sometimes verbose.** It has no effect on the
  outcome, which is decided before the call, and the prompt was not tuned
  further given time constraints.

## Team

- Anika Soni
- Prabhjot Singh
