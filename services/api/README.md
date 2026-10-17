# API and recommendation agent

The service contains the FastAPI API and the evidence-grounded recommendation
workflow used by both the terminal CLI and React web application. The workflow
uses:

- LangGraph `StateGraph` for explicit control flow;
- Gemini through `langchain-google-genai` for structured taste interpretation,
  candidate extraction, metadata verification, and ranking;
- Tavily through `langchain-tavily` for bounded web search;
- Pydantic models at every model/tool boundary;
- OpenCC normalization for Simplified/Traditional Chinese title identity;
- deterministic validation before any candidate becomes a recommendation.

`POST /api/recommend` accepts one natural-language request and invokes the same
compiled LangGraph used by the CLI. No database, authentication, or raw
conversation persistence is included in this milestone. An optional local JSON
store persists only the structured reader profile for CLI testing; the HTTP
endpoint is intentionally stateless for now.

## Workflow

```text
START
  -> build_taste_profile      (Gemini -> structured ReaderTasteProfile)
  -> search_reference_records (Tavily -> official-domain lookup, when supplied)
  -> verify_references        (Gemini claims + deterministic URL/evidence checks)
  -> plan_search              (Gemini -> personalized discovery queries)
  -> discover_candidates      (Tavily -> recommendation/review evidence)
  -> extract_candidates       (Gemini -> titles/authors/opinions; code deduplicates)
       | insufficient and retry available
       ` -> revise_search -> discover_candidates -> extract_candidates
  -> search_candidate_records (Tavily -> one bounded official lookup per candidate)
  -> verify_candidates        (objective metadata vs attributed reader opinions)
  -> rank_candidates          (taste fit + hard filters + evidence-quality penalty)
  -> END
```

Discovery is limited to two initial searches plus one revised search and at
most two rounds. Reference and candidate verification are separately capped by
`AGENT_MAX_REFERENCE_BOOKS` and `AGENT_MAX_VERIFICATION_CANDIDATES`. Search
snippets are untrusted evidence, not instructions. The workflow may return
fewer than the requested number of books when verification or hard-filter
evidence is insufficient.

Gemini calls explicitly retry transient HTTP 503 failures with exponential
backoff. Set `AGENT_FALLBACK_MODEL` to opt into a second model after primary
retries are exhausted; leave it blank to disable fallback.

## Install

From `services/api` with the existing virtual environment:

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

Or with `uv`:

```bash
uv sync --extra dev
```

## Configure live providers

From the repository root:

```bash
cp .env.example .env
```

Edit `.env` and provide:

```dotenv
GOOGLE_API_KEY=your-google-ai-studio-key
TAVILY_API_KEY=your-tavily-key
AGENT_MODEL=gemini-3.8-flash
AGENT_FALLBACK_MODEL=
```

The remaining budgets and timeouts are documented in `.env.example`. Never
commit `.env`; it is ignored by Git.

## Run a live recommendation

From `services/api`:

```bash
.venv/bin/python -m find_my_next_book_api.cli recommend \
  "推荐一些已完结的古言权谋小说，女主聪明，不要虐文"
```

Add `--verbose` to print graph transitions as they occur:

```bash
.venv/bin/python -m find_my_next_book_api.cli recommend \
  "推荐一些已完结的古言权谋小说，女主聪明，不要虐文" \
  --verbose
```

To retain a structured taste profile between CLI runs, give it a local session
ID. Feedback and already-read titles are merged by Gemini into that profile:

```bash
.venv/bin/python -m find_my_next_book_api.cli recommend \
  "我喜欢《我在无限游戏里封神》，因为副本烧脑、主角聪明、群像好。想找类似BL无限流，感情线不要盖过剧情。" \
  --session reader-1 \
  --read "地球上线" \
  --verbose

.venv/bin/python -m find_my_next_book_api.cli recommend \
  "再推荐一批，节奏快一些" \
  --session reader-1 \
  --feedback "上次推荐的感情线还是偏多"

.venv/bin/python -m find_my_next_book_api.cli profile reader-1
```

Local profiles live under `.novelscout/sessions/` by default and are ignored by
Git. They contain structured taste fields and the last recommendation titles,
not raw chat transcripts or credentials.

The dedicated live smoke command uses that same representative request:

```bash
.venv/bin/python -m find_my_next_book_api.cli smoke-test --verbose
```

The report includes the taste profile, reference resolution, staged search
queries, extracted candidates, verification status, objective metadata,
attributed opinions, grounded recommendations, uncertainty notes, and run
metrics. Metrics cover canonical-link validity, metadata verification, hard
filter compliance, duplicate rate, and provider failures.

Two same-reference/different-taste fixtures live in
`evaluation/personalization_scenarios.json`. They are designed to reveal whether
ranking changes when the reader values puzzle/ensemble qualities versus
emotional bonds. Automated tests use mocked providers; they do not prove live
Gemini/Tavily quality.

## Test

Mocked tests do not call external services:

```bash
.venv/bin/ruff check .
.venv/bin/pytest -m 'not live'
```

Run the separately marked live integration test only when credentials are set
and API usage is intended:

```bash
RUN_LIVE_TESTS=1 .venv/bin/pytest -m live -s
```

Run the FastAPI foundation independently with:

```bash
.venv/bin/uvicorn find_my_next_book_api.main:app --reload --port 8000
```

With the server running, the React application sends:

```http
POST /api/recommend
Content-Type: application/json

{"request":"推荐一些已完结的古言权谋小说，女主聪明，不要虐文"}
```

The response contains the structured reader profile, grounded recommendations,
provider names, verification status, source evidence, and run metrics. Missing
credentials return `503`, quota exhaustion returns `429`, and provider/workflow
failures return `502` with a safe user-facing error message. Local CORS permits
`http://localhost:5173` by default and can be changed with
`APP_CORS_ORIGINS`.

