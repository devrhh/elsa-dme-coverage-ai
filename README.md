# Coverage Q&A Service

A multi-tenant service that lets Durable Medical Equipment (DME) companies upload coverage PDFs and ask natural-language questions, getting back an answer a rep can verify in under two minutes - grounded in retrieval, with citations, a confidence signal, and a human-review flag when the system isn't sure.

## Contents

- [Quick start](#quick-start)
- [Frontend](#frontend)
- [API overview](#api-overview)
- [Architecture](#architecture)

## Quick start

### 1. Prerequisites

- Python 3.11+
- Docker (for Postgres) - or point `DATABASE_URL` at any Postgres instance you already have
- A free [Groq](https://console.groq.com/keys) API key (for chat/answer-generation only -
  see [Why Groq + local embeddings](#why-groq-for-chat--a-local-model-for-embeddings))

Embeddings run locally (no API key, no network call) via `fastembed`, so the only external
dependency at runtime is Groq for chat completions.

### 2. Start Postgres

```bash
docker compose up -d
```

This starts Postgres on `localhost:5433` (mapped from the container's `5432`, to avoid
clashing with a local Postgres install) with the credentials in `docker-compose.yml`.

### 3. Set up the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set `GROQ_API_KEY` to a real key from
[console.groq.com/keys](https://console.groq.com/keys). The other defaults (database URL,
storage paths, caps/timeouts) already match `docker-compose.yml` and should work as-is.

### 5. Initialize the database

```bash
python init_db.py
```

Creates the schema and seeds three sample organizations (`Acme DME`, `MedSupply Co`,
`HomeHealth Partners`) - see [Why organizations are pre-seeded](#why-organizations-are-pre-seeded-not-crud-managed).

### 6. Run the service

```bash
uvicorn app.main:app --reload
```

- App + frontend: [http://localhost:8000](http://localhost:8000)
- Interactive API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health check: `GET /health`

The first time a PDF is uploaded or a question is asked, the local embedding model
(`BAAI/bge-large-en-v1.5`, ~1.2GB) downloads once and is cached under `data/models/` -
after that, embedding runs fully offline.

## Frontend

A plain HTML/CSS/JS single page, served directly by FastAPI as static files at `/`
(`app/static/`). It covers the full flow end-to-end:

- **Organization picker** - a dropdown populated from `GET /organizations`; every other
  action is scoped to the selected org.
- **Documents** - upload a PDF (`POST /documents`), see status/page/chunk counts, delete
  (`DELETE /documents/{id}`).
- **Ask a question** - submits to `POST /query` and renders the answer, confidence badge,
  a "needs human review" flag, latency, and resolved citations (filename, page, section).
- **Feedback** - thumbs up/down on the most recent answer, posted to
  `POST /interactions/{id}/feedback`.
- **Analytics** - most-queried documents, most frequent questions, and weekly
  per-document query counts, with a manual refresh button.

It's intentionally simple (no framework, no bundler) since the focus here is the
backend; see `app/static/app.js` for the ~10 fetch calls that wire it to the API above.

## API overview

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/organizations` | List the pre-seeded organizations (for the picker). |
| `POST` | `/documents` | Upload a PDF for an org; runs ingestion synchronously and returns the resulting document (with `status`). |
| `GET` | `/documents?org_id=...` | List an org's documents. |
| `DELETE` | `/documents/{document_id}?org_id=...` | Delete a document and its indexed chunks. |
| `POST` | `/query` | Ask a question; returns a grounded answer with citations, confidence, and a human-review flag. |
| `POST` | `/interactions/{interaction_id}/feedback` | Record a thumbs up/down on a previous answer. |
| `GET` | `/analytics?org_id=...` | Most-queried documents, frequent questions, weekly usage. |
| `GET` | `/health` | Liveness check. |

Full request/response schemas are in the interactive docs at `/docs` once the server is
running.

## Architecture

```
app/
  main.py                  FastAPI app setup, static frontend mount, exception handlers
  config.py                Central settings (env-driven, pydantic-settings)
  db/
    models.py              Organization, Document, Interaction, InteractionDocument
    session.py             SQLAlchemy engine/session
    types.py                Portable UUID column type (Postgres native / SQLite CHAR(36))
  schemas/                Pydantic request/response contracts
  routers/                organizations, documents, query, feedback, analytics
  static/                 Frontend (index.html, app.js, styles.css) - served at "/"
  services/
    pdf_processing.py     Validation + layout-aware structural extraction (pdfplumber)
    chunking.py            Structure-aware chunking (headings/paragraphs/lists/tables)
    embeddings.py          Local ONNX embeddings (bge-large-en-v1.5 via fastembed, no API key, batched)
    vector_store.py        ChromaDB wrapper - one collection per organization
    retrieval.py           Retrieval + similarity-based confidence gate
    answer_generation.py   Guarded prompt + JSON-mode generation via Groq
    ingestion.py           Orchestrates extract -> chunk -> embed -> index -> record
    analytics_service.py   SQL aggregation queries for the analytics endpoint
  core/
    exceptions.py          Typed application errors -> clean HTTP responses
    timeouts.py             Subprocess-based hard timeout for untrusted PDF parsing
docker-compose.yml        Postgres service for local development
init_db.py                Schema creation + sample organization seeding
```

## Key design questions

**Why FastAPI vs Flask?**
Async-capable (room to move to true non-blocking I/O later), native Pydantic validation
for both request/response contracts and LLM output schemas, auto-generated OpenAPI docs
(`/docs`), and modern type-hint-based DX - Flask needs extra libraries (Marshmallow,
Flask-RESTX) to match any of that out of the box.

**RAG architecture**
Upload -> validate PDF -> extract structure (`pdfplumber`) -> structure-aware chunk ->
embed locally -> index into an org-scoped Chroma collection. Query -> embed question ->
search only that org's collection -> confidence gate -> if confident, guarded prompt to
Groq (JSON mode) -> validate + verify citations -> persist + return answer with
citations, confidence, and a review flag.

**Chunking strategy**
Structure-aware, not fixed-size: headings are tracked as a path and prefixed to every
chunk; tables are split by row-group with the header repeated; bullet/numbered lists are
kept whole with their lead-in sentence; prose is token-budgeted (~550 tokens, `tiktoken`
`cl100k_base`) with ~120-token sliding overlap. Each content type is chunked differently
because one generic splitter scrambles tables and fragments list context.

**Embedding model choice**
`BAAI/bge-large-en-v1.5` (1024-dim), run locally via `fastembed` (ONNX, CPU). Chosen over
the smaller default `all-MiniLM-L6-v2` for meaningfully better MTEB retrieval quality, at
the cost of a larger one-time download (~1.2GB) and slower per-chunk CPU inference - both
fully offline, no API key either way.

**Vector database choice**
ChromaDB, embedded/persistent mode (no separate server to run) - one **physically
separate collection per organization**, which is also the strongest layer of tenant
isolation (no shared index to leak across even if a filter is forgotten). Trade-off:
doesn't scale as gracefully to thousands of orgs.

**How organization isolation is enforced**
Three independent layers: (1) API layer validates `org_id` on every request, (2) SQL
layer filters every query `WHERE org_id = ...`, (3) vector layer uses a separate Chroma
collection per org. No single layer's mistake can leak data across tenants. No auth
yet - `org_id` is trusted from the request, not a verified identity (the biggest gap,
flagged for production).

**How hallucinations are prevented**
Layered: retrieval grounding (model only sees retrieved chunks) -> similarity-confidence
gate (skips the LLM entirely on weak matches) -> prompt-injection defense (retrieved text
wrapped as inert data) -> structured JSON output validated against a Pydantic schema with
bounded retries -> independent verification that every citation actually came from the
retrieved set -> low temperature (0.1) -> model self-reports a review flag, combined with
the independent confidence signal.

**Path to production**
In priority order: real auth (API keys/JWT scoped to org), a background job queue for
ingestion (currently synchronous), Alembic migrations (currently `create_all()`),
re-validating the similarity threshold for the current embedding model, hybrid
search/re-ranking, classifying non-document questions before retrieval, observability
(logs/tracing/metrics), rate limiting, a managed vector store for horizontal scale, and
an automated test suite + CI/CD.
