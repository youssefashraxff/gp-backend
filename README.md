# gp-backend

Backend for the Concept Development GP: a multi-agent system that turns an Egyptian site into a full commercial concept package, escalating to a human expert instead of guessing.

## Shape

One codebase (**modular monolith**), started as **two processes**:

| Process | Entry point | Job |
|---|---|---|
| API | `app/api/main.py` | Requests, WebSocket progress to the browser |
| Worker | `app/worker/main.py` | Temporal worker that runs the agents |

```
app/
  api/            FastAPI routes + WebSocket
  worker/         Temporal worker
  orchestrator/   Temporal workflows: the flow BETWEEN phases
  phases/
    research/       interface.py is the only public entry point
    brand_design/
    visuals/
    investment/
  shared/         phase contract, hashing, generated schema types, (later) HITL, RAG, tools, model routing
schemas/          git submodule -> gp-schemas
```

**Module rule:** code may only import another phase through its `interface.py`.

**Who owns what:** Temporal owns phase order, approvals, retries and waiting for the expert. LangGraph owns everything inside a phase, including the checkpoint an escalation resumes from.

**Edit propagation:** field-level. Each phase declares the fields it reads (`READS`) and the reads are also recorded at run time. Every field carries a content hash, so an edit that doesn't change a value reruns nothing.

## Getting started

```bash
git clone --recurse-submodules <repo-url>
cd gp-backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
docker compose up -d          # Temporal on :7233, UI on http://localhost:8233
uvicorn app.api.main:app --reload
pytest
```

Already cloned without submodules? `git submodule update --init`.
After every pull: `git submodule update` (keeps `schemas/` on the pinned commit).

## Schema types

```bash
bash scripts/generate_types.sh
```
Commit the regenerated `app/shared/schemas_generated/` together with any submodule bump. CI fails if they don't match.

## Workflow

- `main` = production, `develop` = integration. Branch from `develop`, PR back into `develop`.
- Branch names: `feature/<clickup-id>-short-name`, `fix/<clickup-id>-short-name`.
- Every PR is reviewed by Youssef. Done = merged into `develop`.
- CI on every PR: Ruff (lint + format), schema check, Pyright (basic), pytest.
