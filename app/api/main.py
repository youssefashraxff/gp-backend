"""API process entry point.

Run locally:  uvicorn app.api.main:app --reload

Sprint 0 adds: POST /concepts (starts a Temporal workflow) and
/ws/concepts/{id} (pushes progress read from Temporal).
"""

from fastapi import FastAPI

app = FastAPI(title="Concept Development GP API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
