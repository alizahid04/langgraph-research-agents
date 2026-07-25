# Intellisys — Multi-Agent Research & Decision Intelligence Platform

A production-style reference implementation of a multi-agent research system:
a **Supervisor** plans, **Research** agents gather real evidence in parallel
via Tavily, an **Analyst** synthesizes findings, a **Critic** gates quality
with a bounded revision loop, and a **Writer** produces a genuinely
topic-adaptive, cited Markdown report — via real OpenRouter LLM calls,
orchestrated with **LangGraph** behind a **FastAPI** backend, with a
glassmorphism SaaS dashboard on top.

> **This build requires real API keys.** There is no mock mode: if
> `OPENROUTER_API_KEY` or `TAVILY_API_KEY` is missing, the API rejects new
> runs with a clear `400` error instead of silently generating synthetic
> content. See **Configuration** below.

---

## Architecture

```
START
  │
  ▼
Request Analysis  ── Supervisor step 1: decide if the objective is clear
  │                   enough to plan, or genuinely ambiguous
  │
  ├─ Ambiguous (and clarification round not yet used) ──► pause, return to User
  │                                                         (resume via
  │                                                          POST /api/workflows/{id}/clarify,
  │                                                          capped at 1 round so it can
  │                                                          never pause forever)
  ▼
Planning  ── Supervisor step 2: produce the research plan
  │  (ResearchPlan: 3-6 topic-specific research questions)
  ▼
Research    ── parallel real web search (Tavily) + evidence storage
  │  (EvidenceItem[] with source_title / source_url / snippet)
  ▼
Analyst     ── evidence-only, builds insights + comparison table (only if relevant)
  │  (AnalysisResult)
  ▼
Critic      ── APPROVED | REVISION_REQUIRED (max 2 revision cycles)
  │
  ├─ REVISION_REQUIRED, root cause = weak analysis ──► back to Analyst (same evidence)
  ├─ REVISION_REQUIRED, root cause = evidence gap  ──► back to Research
  │                                                     (gap-filling queries only,
  │                                                      not the whole plan re-run)
  │
  └─ APPROVED
       ▼
     Writer  ── export-only; LLM writes an adaptive report body,
       │        deterministic References section appended from real evidence
       ▼
      END
```

Every agent-to-agent handoff is a typed **Pydantic** model (`app/schemas.py`)
— no raw chat history is ever passed between agents. Tool access is
restricted per agent (see `allowed_tools` on each agent class):

| Agent      | Tools                     |
|------------|---------------------------|
| Supervisor | none (planning only)      |
| Research   | search, evidence storage  |
| Analyst    | evidence retrieval (read) |
| Critic     | none (reviews JSON only)  |
| Writer     | export                    |

### Why the report is topic-adaptive, not generic

The Writer agent does not assemble a fixed Python template. It sends the
plan, numbered evidence, and analysis to the LLM with instructions to choose
and order sections based on what the topic actually needs (a technical
survey reads differently from a build-vs-buy memo), then deterministically
appends a `## References` section built from the real evidence URLs — so
citations are always genuine, never model-hallucinated.

### The clarification loop

If the objective is genuinely ambiguous ("AI in healthcare" could mean
diagnostics, hospital operations, or drug discovery), the Supervisor's
request-analysis step pauses the run instead of guessing. The run's status
becomes `awaiting_clarification` and `clarification_question` is populated;
the dashboard's Live Monitor shows an inline prompt. Submitting an answer to
`POST /api/workflows/{id}/clarify` resumes the run as a fresh graph
invocation with the answer folded in. **Capped at one round** — if the
Supervisor would still want to ask again on the resumed pass, the cap
forces it to proceed with its best interpretation anyway, guaranteeing the
run can never pause indefinitely.

### Critic-driven revision routing

When the Critic requests a revision, it also names the root cause:
`revision_target: "research"` (the evidence itself is too thin — the Critic
also supplies 1-3 gap-filling search queries) or `revision_target:
"analyst"` (the evidence is adequate but the synthesis was weak). The graph
routes accordingly — re-running Research only for the specific gap
identified, not the whole plan, or re-running the Analyst against the same
evidence. Both paths still count against the shared revision cap (default 2).

> **A LangGraph gotcha worth knowing if you extend this:** conditional-edge
> routing functions (`route_after_critic`, `route_after_request_analysis`)
> can *read* state to decide where to go, but any mutations they make to
> that state are silently discarded — only state returned from an actual
> *node* function gets merged back into the graph. Early in building this
> feature, `revision_count` and the gap-filling question list were being
> set inside the routing functions and quietly never took effect. The fix:
> all state writes happen in `critic_node`/`request_analysis_node`
> themselves; the routing functions only read already-committed state.


## Tech Stack

**Backend:** Python, FastAPI, LangGraph, LangChain-core, Pydantic, SQLAlchemy,
Alembic, SQLite, httpx (OpenRouter + Tavily clients), tenacity (network-only
retries), Docker.

**Frontend:** HTML5 / CSS3 / vanilla ES6 (no build step), Lucide icons,
marked.js for Markdown rendering. Glassmorphism dark/light/system theme with
a blocking init script (no flash-of-wrong-theme) and full persistence.
`/` **is** the dashboard — there is no separate landing page.

## Project Structure

```
research-intelligence-platform/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + static frontend mount
│   │   ├── config.py            # Settings (.env)
│   │   ├── exceptions.py        # LLMNotConfiguredError, SearchNotConfiguredError, ReportGenerationError
│   │   ├── database.py          # SQLAlchemy engine/session
│   │   ├── models.py            # ORM: workflow_runs, tasks, evidence, reports, execution_logs
│   │   ├── schemas.py           # Pydantic handoff contracts + API I/O models
│   │   ├── llm_client.py        # OpenRouter client (real calls, retries scoped to network errors only)
│   │   ├── logging_config.py
│   │   ├── tools/
│   │   │   ├── search_tool.py   # Tavily wrapper — raises if not configured
│   │   │   ├── evidence_tool.py # store/retrieve evidence in SQLite
│   │   │   └── export_tool.py   # markdown export + citation validator
│   │   ├── agents/
│   │   │   ├── base.py          # shared LLM + execution-trace logging
│   │   │   ├── supervisor.py
│   │   │   ├── research.py
│   │   │   ├── analyst.py
│   │   │   ├── critic.py
│   │   │   └── writer.py        # LLM-authored adaptive report + real references
│   │   ├── graph/
│   │   │   ├── state.py         # WorkflowState TypedDict
│   │   │   └── workflow.py      # LangGraph StateGraph wiring + revision loop
│   │   └── api/
│   │       └── routes_workflow.py  # create (fail-fast config check)/list/detail/stats/download
│   ├── tests/                   # pytest suite — real logic, network calls replaced with test doubles
│   ├── alembic/                 # migration scaffold (initial schema via create_all)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html               # the dashboard — this IS the app, no landing page
│   ├── css/{theme,dashboard}.css
│   └── js/{theme,api,dashboard}.js
├── docker-compose.yml
├── .env.example
└── README.md
```

## Installation

### Option A — Local (Python)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env
# edit .env and set OPENROUTER_API_KEY and TAVILY_API_KEY
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** — this is the dashboard directly.

### Option B — Docker

```bash
cp .env.example .env   # then set your real API keys
docker compose up --build
```

### Running tests

```bash
cd backend
pytest -q
```

All tests run offline: real network calls to OpenRouter/Tavily are replaced
with deterministic test doubles (`conftest.py`'s `patched_llm` /
`patched_search` fixtures) — this is standard test isolation, not an
application feature. The app itself has no mock mode.

## Configuration

Copy `.env.example` to `.env` and set both keys — **both are required**:

| Variable              | Purpose                                         |
|------------------------|--------------------------------------------------|
| `OPENROUTER_API_KEY`  | **Required.** Enables real LLM calls via OpenRouter |
| `OPENROUTER_MODEL`    | Model string, e.g. `openrouter/anthropic/claude-3.5-sonnet` |
| `TAVILY_API_KEY`      | **Required.** Enables real web search            |
| `DATABASE_URL`        | Defaults to local SQLite file                    |
| `MAX_REVISIONS`       | Critic revision-loop cap (default 2)             |

If either key is missing, `POST /api/workflows` returns `400` immediately
with a message naming exactly which key is missing — the platform never
falls back to synthetic content.

## API Overview

| Method | Path                                | Purpose                          |
|--------|--------------------------------------|-----------------------------------|
| POST   | `/api/workflows`                    | Create + launch a workflow run (400 if not configured) |
| POST   | `/api/workflows/{id}/clarify`       | Answer a paused run's clarifying question and resume it (409 if not awaiting clarification) |
| GET    | `/api/workflows`                    | List all runs                     |
| GET    | `/api/workflows/stats`              | Dashboard aggregate stats         |
| GET    | `/api/workflows/{id}`               | Full run detail (tasks, evidence, reports, logs) |
| GET    | `/api/workflows/{id}/report/download` | Download the latest report as `.md` |
| GET    | `/api/health`                       | Health check + `openrouter_configured` / `tavily_configured` flags |

The dashboard polls `GET /api/workflows/{id}` every 1.5s while a run is
selected in the **Live Monitor** tab to animate the workflow graph, agent
cards, and execution timeline.

## Known remaining issues / suggested improvements

- **Streaming** — replace polling with Server-Sent Events / WebSockets for the live monitor.
- **Human-in-the-loop approval checkpoints** — the clarification loop covers "is the objective clear enough to plan," but there's still no pause for a human to approve the plan or the final analysis before the Writer runs (only the Critic gates that automatically).
- **Optional agents** — Fact Checker, Citation Validator, Risk Analyst as additional graph nodes behind feature flags.
- **Auth & multi-tenancy** — per-user workspaces, API keys, rate limiting.
- **Richer citation validation** — `tools/export_tool.py`'s `validate_citations()` only checks that referenced URLs exist in stored evidence; it doesn't verify the *claim* actually matches the *snippet*, and it isn't wired into the Writer's output automatically yet.
- **Alembic migrations** — the scaffold is in place; generate real revisions instead of `create_all` once the schema stabilizes. If you're upgrading an existing `research_platform.db` from before the clarification feature, delete it (or add a migration) — `create_all()` only creates missing tables, it doesn't add new columns to existing ones, so the new `clarification_*` columns on `workflow_runs` won't appear on an old DB file without a fresh start.
- **Structured tracing/observability** — OpenTelemetry spans per agent/tool call.

## License

MIT — use this as a starting point for your own project.
