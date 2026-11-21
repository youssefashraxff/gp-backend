"""API process entry point.

Run locally:  uvicorn app.api.main:app --reload

Sprint 0 adds: POST /concepts (starts a Temporal workflow) and
/ws/concepts/{id} (pushes progress read from Temporal).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from temporalio.client import Client

from app.api.routes.concepts import router as concepts_router
from app.api.websocket import router as websocket_router
from app.shared.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.temporal_client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    yield


app = FastAPI(title="Concept Development GP API", lifespan=lifespan)  # type: ignore
app.include_router(concepts_router)
app.include_router(websocket_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
