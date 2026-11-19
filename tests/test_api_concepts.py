"""API tests for POST /concept, the progress WebSocket, and CORS.

No real Temporal server is used: a fake client replaces the real one via
FastAPI dependency overrides, and TestClient is used without a `with` block
so the app lifespan (which connects to Temporal) never runs.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from temporalio.service import RPCError, RPCStatusCode

from app.api.deps import get_temporal_client
from app.api.main import app
from app.orchestrator.constants import TASK_QUEUE
from app.shared.schemas_generated.concept_input_schema import ConceptInput
from app.shared.schemas_generated.progress_event_schema import ProgressEvent

VALID_INPUT = {"site": {"name": "Giza", "lat": 30.0, "lng": 31.2}}


class FakeTemporalClient:
    """Stands in for temporalio.client.Client and records start_workflow calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.error: Exception | None = None

    async def start_workflow(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error


@pytest.fixture
def fake_client() -> Iterator[FakeTemporalClient]:
    fake = FakeTemporalClient()
    app.dependency_overrides[get_temporal_client] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client(fake_client: FakeTemporalClient) -> TestClient:
    # No `with` block: the lifespan (real Temporal connection) must not run.
    return TestClient(app)


def test_post_concept_starts_workflow(client: TestClient, fake_client: FakeTemporalClient) -> None:
    response = client.post("/concept", json=VALID_INPUT)

    assert response.status_code == 202
    concept_id = response.json()["concept_id"]
    assert concept_id.startswith("c_")

    assert len(fake_client.calls) == 1
    args, kwargs = fake_client.calls[0]
    assert args == ("ConceptWorkflow",)
    expected_input = ConceptInput.model_validate(VALID_INPUT).model_dump(mode="json")
    assert kwargs["args"] == [concept_id, expected_input]
    assert kwargs["id"] == concept_id
    assert kwargs["task_queue"] == TASK_QUEUE


def test_post_concept_missing_site_returns_422(
    client: TestClient, fake_client: FakeTemporalClient
) -> None:
    response = client.post("/concept", json={})

    assert response.status_code == 422
    assert fake_client.calls == []


def test_post_concept_unknown_field_returns_422(
    client: TestClient, fake_client: FakeTemporalClient
) -> None:
    response = client.post("/concept", json={**VALID_INPUT, "client": "x"})

    assert response.status_code == 422
    assert fake_client.calls == []


def test_post_concept_temporal_failure_returns_503(
    client: TestClient, fake_client: FakeTemporalClient
) -> None:
    fake_client.error = RPCError("temporal is down", RPCStatusCode.UNAVAILABLE, b"")

    response = client.post("/concept", json=VALID_INPUT)

    assert response.status_code == 503


def test_websocket_sends_queued_progress_event(client: TestClient) -> None:
    with client.websocket_connect("/ws/concept/c_test") as websocket:
        data = websocket.receive_json()

    assert data["concept_id"] == "c_test"
    assert data["phase"] == "research"
    assert data["status"] == "queued"
    ProgressEvent.model_validate(data)


def test_cors_allows_configured_origin(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:4200"})

    assert response.headers.get("access-control-allow-origin") == "http://localhost:4200"


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "https://example.com"})

    assert "access-control-allow-origin" not in response.headers
