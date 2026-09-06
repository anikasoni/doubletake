# doubletake frontend

React + Vite + TypeScript + Tailwind UI for the doubletake payment-allocation
backend.

## Prerequisites

- Node 18+ / npm
- The FastAPI backend running on `http://localhost:8000`
  (`uvicorn app.main:app --reload` from the `doubletake/` directory)

## Develop

```
npm install
npm run dev
```

The dev server runs on `http://localhost:5173` (strict port). Requests to
`/api/*` are proxied to the backend with the `/api` prefix stripped, so no CORS
config is needed in development. To point at a backend directly instead, set
`VITE_API_BASE=http://localhost:8000`. The backend also enables
`CORSMiddleware` for `http://localhost:5173`.

## Design system

Defined in `tailwind.config.js` (theme extensions) and `src/index.css` (base
layer). This is a deliberate ledger-tool aesthetic — not the default Tailwind
look:

- Colours: `ink`, `paper`, `paper-raised`, `rule`, `signal-alert`,
  `signal-resolved`, `signal-pending`.
- Type: Source Serif 4 (headings / numeric displays, weight 600), IBM Plex Sans
  (body, labels, chrome). Amounts use `tabular-nums` (`.tnum`) and are
  right-aligned in tables.
- Hairline 1px `rule` borders instead of shadows and rounded card grids.
  Border radius is capped at 2–4px. Sentence case, no all-caps, no
  letter-spacing tricks.

`src/App.tsx` currently renders a token proof sheet only; real screens come
next.

## Files

- `src/types.ts` — TypeScript types mirroring `app/schemas.py`.
- `src/api.ts` — typed fetch wrappers for `GET /payments`,
  `GET /payments/{id}`, `POST /payments/{id}/process`.
