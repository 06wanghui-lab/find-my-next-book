# Find My Next Book

An AI-powered, agentic discovery and recommendation application for Chinese web
novels. Readers describe what they want in natural language; the product finds
real books on platforms such as 晋江文学城、长佩文学、番茄小说 and 起点中文网,
compares the candidates, and returns ranked, evidence-backed recommendations
with links to the original listings.

> Status: working vertical slice. A bounded LangGraph workflow uses Gemini and
> Tavily to produce evidence-grounded recommendations through both the CLI and
> the React application via `POST /api/recommend`.

## Product vision

Finding a Chinese web novel is often a fragmented process: readers translate a
vibe into tags, search several platforms, inspect incomplete metadata, and then
cross-check community discussions. Find My Next Book should make that process
faster without pretending that an LLM already knows the catalogue.

The product will combine conversational preference capture with a bounded,
observable agent workflow. Every recommended title must be associated with
retrieved evidence, a source URL, and enough metadata for the user to verify it.
When evidence is weak or conflicting, the product should say so instead of
inventing a confident answer.

### Product principles

- **Real books, traceable evidence.** Do not present a title unless the system
  can attach a canonical or otherwise verifiable source URL.
- **Recommendation before chat.** The interface is a guided discovery product,
  not an open-ended generic chatbot.
- **Respect data owners.** Prefer official APIs, licensed feeds, approved search
  providers, and user-supplied links. Do not bypass access controls or platform
  terms.
- **Human-understandable automation.** Use an agent where planning and tool use
  add value; keep validation, scoring, and safety rules deterministic.
- **Progressive personalization.** Ship useful session-based recommendations
  before building accounts, long-term profiles, or collaborative filtering.

## Primary user workflows

1. **Describe a reading mood**
   - The reader enters free-form preferences: genre/频道, tropes, themes,
     completed or ongoing status, desired length, hard dislikes, and examples.
   - The system turns this into an editable structured preference brief.

2. **Discover and compare**
   - The agent plans searches, queries the available source adapters, resolves
     duplicate listings, and rejects candidates without sufficient evidence.
   - A ranker compares candidates against positive preferences and exclusions.

3. **Review grounded recommendations**
   - The reader receives a short ranked list with match reasons, caveats,
     metadata provenance, and links to the original platform.
   - The UI makes freshness and missing fields visible.

4. **Refine the result**
   - The reader can say “more like this,” exclude an element, adjust a filter,
     or ask why one result ranked above another without restarting the search.

5. **Improve future recommendations (later phase)**
   - Explicit feedback such as save, dismiss, read, and “not for me” updates a
     user-controlled preference profile.

## Proposed architecture

```text
React/Vite web client
        |
        | HTTPS / JSON (streaming later)
        v
FastAPI application
  |-- request/session API
  |-- LangGraph recommendation workflow
  |     |-- preference interpreter
  |     |-- search planner
  |     |-- source tools/adapters
  |     |-- evidence validator + entity resolver
  |     |-- candidate scorer/reranker
  |     `-- grounded response composer
  |-- deterministic policy and validation layer
  `-- persistence interfaces
        |-- PostgreSQL (sessions, feedback, normalized books)
        `-- pgvector only when semantic retrieval is justified

External boundary
  |-- official/partner APIs and approved feeds
  |-- compliant web-search provider
  `-- curated or user-supplied URLs
```

The initial implementation should remain a **modular monolith**. It is easier to
test, deploy, and explain than a fleet of services, while the provider and
persistence interfaces preserve clean extraction points if scale later demands
it.

### Agent workflow

LangGraph is proposed for a typed, stateful graph rather than an unconstrained
autonomous loop:

1. Parse natural language and feedback into a structured `ReaderTasteProfile`.
2. Resolve any reference novels before using their characteristics for search.
3. Run bounded candidate discovery against recommendation and review sources.
4. Extract, normalize, and deduplicate title/author identities.
5. Search separately for original-platform records and objective metadata.
6. Apply already-read exclusions and hard constraints deterministically.
7. Rank by explicit taste fit and evidence quality while keeping reader opinions
   distinct from verified metadata.
8. Compose a possibly shorter recommendation list with an auditable trace and
   retrieval-quality metrics.

Tool calls should have schemas, timeouts, retry limits, per-request budgets, and
structured results. Retrieved pages and snippets are untrusted data: they must
never be allowed to override system policy or silently become instructions to
the model.

## Technology choices

| Area | Initial choice | Why | Main trade-off |
| --- | --- | --- | --- |
| Web | React + TypeScript + Vite | Fast iteration, strong ecosystem, static deployment | SEO needs deliberate metadata or later SSR/prerendering |
| API | FastAPI + Pydantic | Typed contracts, async I/O, good Python AI ecosystem | Keep domain logic out of route handlers |
| Orchestration | LangGraph | Explicit state, checkpoints, conditional edges, tool calling | More structure than a simple chain; graph state needs discipline |
| Database | PostgreSQL when persistence begins | Durable relational core with strong querying | Requires migrations and managed infrastructure |
| Vector search | pgvector, deferred | Avoids a second datastore and supports later semantic retrieval | Not needed until there is a licensed/curated corpus to embed |
| Package tooling | npm workspaces + `uv`-compatible Python project | Low-friction local setup and reproducible lockfiles | Two language toolchains remain unavoidable |
| Deployment | Static frontend + containerized API + managed Postgres | Portable and understandable | Cross-origin config and two deploy targets |

The terminal milestone uses Gemini behind a small model gateway interface and
Tavily behind a search-provider interface. Both remain replaceable so cost,
latency, privacy, and Chinese-language quality can be evaluated with a
representative test set before the public beta.

## Critical decisions before feature implementation

### 1. Book-data acquisition is the highest-risk dependency

The first engineering spike should produce a per-platform capability matrix:
permitted access method, available fields, freshness, rate limits, stable IDs,
link format, attribution requirements, and terms/contact status.

Preferred acquisition order:

1. official or partner APIs and licensed feeds;
2. platform-approved export, affiliate, or search mechanisms;
3. a compliant third-party web-search API used for discovery, followed by
   source-link verification;
4. curated records and user-supplied links.

Do not make HTML scraping the default integration. `robots.txt` is not a grant
of permission, and technically accessible pages may still be restricted by
terms, authentication, copyright, or rate limits. If a platform does not permit
automated retrieval, the adapter must remain disabled and the UI must be honest
about coverage.

Search snippets can help locate candidates but are weak evidence: they may be
stale, truncated, or copied. Store provenance at field level where practical and
distinguish canonical metadata from inferred tags and model-generated summaries.

### 2. Keep the agent bounded and evaluation-friendly

A single “research agent” would be fast to prototype but difficult to debug,
control, and evaluate. The proposed graph separates interpretation, retrieval,
normalization, filtering, ranking, and writing. This makes it possible to replay
stored provider results, test ranking without network calls, and inspect why a
book was removed or promoted.

The recommendation quality plan should include a small, hand-reviewed Chinese
evaluation set before prompt tuning: preference briefs, expected hard filters,
plausible candidates, citation validity, and explanation faithfulness.

### 3. Defer infrastructure that does not yet improve recommendations

- Start without Redis, a message broker, or a separate vector database.
- Add PostgreSQL when sessions, book snapshots, or feedback need persistence.
- Add background jobs only when provider latency exceeds an interactive request
  budget or scheduled catalogue refresh is authorized.
- Add authentication after the anonymous discovery loop works; it can be added
  earlier only if provider or abuse controls require it.
- Treat OpenClaw as a future adapter at the model/tool boundary, not as a core
  domain dependency.

### 4. Deploy for portability and operational clarity

The frontend can be hosted on a static edge platform; the API should ship as a
standard container; persistence should use managed PostgreSQL in the same region
as the API. The exact vendors should be chosen after checking current regional
availability, pricing, data-processing terms, streaming support, and sleep/cold
start behavior.

For public beta, plan for HTTPS, separate preview/production environments,
secret management, CORS allowlists, request and provider timeouts, rate limits,
structured logs, trace IDs, health checks, error reporting, database backups,
and a visible privacy/data-source policy.

## Repository layout

```text
find-my-next-book/
├── apps/
│   └── web/                       # React/Vite client
├── services/
│   └── api/                       # FastAPI application and tests
│       └── src/find_my_next_book_api/
│           ├── agents/            # LangGraph definitions and typed state
│           ├── api/               # HTTP routes and transport schemas
│           ├── core/              # settings and cross-cutting policy
│           ├── persistence/       # local structured CLI sessions (initially JSON)
│           ├── providers/         # compliant external data adapters
│           └── recommendation/    # normalization, verification, filtering, ranking
├── docs/
│   └── decisions/                 # lightweight architecture decisions
├── .github/workflows/             # continuous integration
├── .env.example                   # documented, non-secret configuration
└── package.json                   # JavaScript workspace commands
```

Empty package boundaries are intentional markers for the next vertical slice;
they should not become dumping grounds. Dependencies should point inward toward
domain models and interfaces, while external SDKs stay in adapter modules.

## Local development

Prerequisites: Node.js 22+, npm 10+, Python 3.12+, and optionally
[`uv`](https://docs.astral.sh/uv/).

```bash
# One-time web install (repository root)
npm install

# One-time API install
cd services/api
uv sync --extra dev
```

Copy `.env.example` to `.env` at the repository root and add `GOOGLE_API_KEY`
and `TAVILY_API_KEY`. Never put provider keys in a `VITE_` variable: Vite
variables are bundled into browser code.

Start the two development servers in separate terminals:

```bash
# Terminal 1: backend
cd services/api
uv run uvicorn find_my_next_book_api.main:app --reload --port 8000

# Terminal 2: frontend, from the repository root
npm run dev:web
```

Then open `http://localhost:5173`, enter a Chinese-language recommendation
request, and select **帮我找下一本**. The browser calls the backend at
`http://localhost:8000/api/recommend`; Gemini and Tavily credentials remain on
the backend. Interactive API documentation is available at
`http://localhost:8000/docs`.

### Checks

```bash
npm run check
npm run test:web
npm run build:web
cd services/api
uv run ruff check .
uv run pytest
```

The JavaScript dependency tree is committed in `package-lock.json`. Generate and
commit `uv.lock` when the team standardizes on `uv` for Python environments; CI
currently installs the declared Python ranges directly.

## Phased plan to public beta

Target: a usable public beta by **30 November 2026**.

| Phase | Target dates | Exit criteria |
| --- | --- | --- |
| 0. Foundation | 17–19 Oct | Repository, architecture, CI, local skeleton |
| 1. Data feasibility | 20–26 Oct | Platform capability matrix; one compliant end-to-end retrieval path; normalized evidence model |
| 2. Recommendation slice | 27 Oct–7 Nov | Preference brief → retrieval → filtering/ranking → cited results; replayable tests |
| 3. Feedback and persistence | 8–16 Nov | Sessions, saves/dismissals, PostgreSQL migrations, basic evaluation dashboard/report |
| 4. Product and deployment | 17–23 Nov | Polished responsive flow, accessibility pass, production environments, observability |
| 5. Beta hardening | 24–30 Nov | Security/rate-limit review, load smoke test, privacy/source documentation, beta launch checklist |

Scope protection matters. A beta can support a limited subset of platforms or
metadata fields if it labels coverage accurately. It should not claim broad
coverage by using brittle or unauthorized acquisition methods.

## Immediate next milestone

Before connecting React, run and evaluate the terminal workflow against a small
hand-reviewed Chinese prompt set. Record search coverage, title/link validity,
hard-filter accuracy, unsupported-claim rate, latency, and cost. Use those
results to decide whether general web search is sufficient for beta or which
official/partner source adapter should be implemented first.

## Documentation

- [Architecture decision log](docs/decisions/README.md)
- [Initial architecture decision](docs/decisions/0001-modular-monolith-and-bounded-agent.md)
- [Book data acquisition policy](docs/decisions/0002-evidence-first-data-acquisition.md)

