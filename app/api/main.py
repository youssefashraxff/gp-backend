"""API process entry point.

Run locally:  uvicorn app.api.main:app --reload

Sprint 0 adds: POST /concepts (starts a Temporal workflow) and
/ws/concepts/{id} (pushes progress read from Temporal).
"""

from app.shared.settings import settings
from temporalio.client import Client

from app.api.routes.concepts import router as concepts_router

from fastapi import FastAPI


async def lifespan(app: FastAPI):
    app.state.temporal_client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    yield


app = FastAPI(title="Concept Development GP API",lifespan=lifespan) # type: ignore
app.include_router(concepts_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

