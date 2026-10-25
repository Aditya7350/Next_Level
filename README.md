# Adaptive Interview Platform

Backend foundation for a text-first adaptive interview product. The API separates answer evaluation, RAG retrieval, question selection, and interview state so each part can evolve independently.

## Requirements

- Python 3.12 or newer
- `uv` package manager

## Run locally (PowerShell)

```powershell
uv sync --extra dev
uv run uvicorn backend.app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`. Open `/docs` for interactive API docs. Liveness checks are at `/health` and `/api/v1/health`; the complete route guide is in [docs/api.md](docs/api.md).

Open `http://127.0.0.1:8000/demo/` for the browser-based candidate interview demo. It exercises the local API and uses the current keyword-based evaluation, so its score is illustrative only.

## Project structure

- `backend/app/api`: versioned routes and authentication dependencies
- `backend/app/core`: settings and cross-cutting concerns
- `backend/app/schemas`: request and response contracts
- `backend/app/services`: application services and local repository prototype
- `backend/app/static`: local candidate interview demo UI
- `backend/app/ai`: answer evaluation and question generation
- `backend/app/rag`: ingestion, embeddings, retrieval, and ranking
- `backend/app/interview`: interview state machine and session rules
- `docs`: architecture and API guides

The current API is a runnable local MVP. Its records and sessions are in memory; persistent storage, managed auth, LLM-backed evaluation, and vector search are follow-on integrations. Candidate code execution remains disabled until an isolated sandbox is configured.
