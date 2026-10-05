# Compliance Intelligence Copilot — frontend

React + TypeScript SPA for the Compliance Intelligence Copilot API.

```bash
npm install
npm run dev        # http://localhost:3000, proxies /api to http://127.0.0.1:8000
npm run verify     # typecheck + lint + tests + production build
```

Requires **Node ≥ 20.19** (Vite 8) and the backend running (`python main.py serve` from the
repository root).

## Why it is built this way

**Types are generated, not written.** `src/types/api.d.ts` comes from the backend's own
OpenAPI schema via `npm run gen:api`. A renamed Pydantic field becomes a TypeScript compile
error instead of a runtime `undefined`. Writing this frontend immediately exposed two
weakly-typed backend endpoints (`/api/stats` returned a bare dict, upload failures were
`list[dict[str, str]]`); both were given real response models rather than papered over with
casts here.

**Streaming is hand-rolled on fetch, not EventSource.** The chat endpoint is a POST with a
JSON body and an auth header, which `EventSource` cannot do. `src/lib/stream.ts` reads the
`ReadableStream` and parses SSE frames directly — about 30 lines, and cancellation via
`AbortController` comes free. It is the riskiest code here, so it has the most tests
(arbitrary chunk boundaries, multiple frames per chunk, malformed frames, pre-stream HTTP
errors, aborts).

**No component library.** The component set needed is small, and the one genuinely hard
primitive — a modal with focus trapping and Escape handling — is solved by the native
`<dialog>` element. That avoids Radix/shadcn entirely while keeping accessibility
standards-based: real buttons, real ARIA, platform focus management.

**Honesty rules are enforced in the UI, not just the API.** An evidence band never renders as
a percentage; a null page number reads "not applicable (no pages in source format)" rather
than being hidden; unreported token usage says "not reported" rather than "0"; status is
always icon + label so colour is never the only signal.

## Layout

```
src/
├── app/           router, providers, shell, theme
├── pages/         Dashboard · Chat · Documents · DocumentDetail · Evaluation · Settings
├── features/chat/ streaming state machine, answer rendering, citation chips, source panel
├── components/    ui.tsx (primitives) · domain.tsx (evidence, conflicts, status)
├── lib/           api client · SSE client · formatting · query keys
└── types/         api.d.ts (generated — do not edit by hand)
```

## Tests

```bash
npm test
```

15 tests over the two pieces where a bug would be invisible but damaging: SSE frame
reassembly, and citation rendering (a `[1]` must be a real chip resolving to a real passage,
and an unresolved reference must stay plain text rather than becoming a dead link).
