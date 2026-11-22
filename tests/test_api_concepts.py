"""API tests for POST /concept, the progress WebSocket, and CORS.

No real Temporal server is used: a fake client replaces the real one via
FastAPI dependency overrides, and TestClient is used without a `with` block
so the app lifespan (which connects to Temporal) never runs.
"""

import asyncio
from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from temporalio.converter import DataConverter
from temporalio.service import RPCError, RPCStatusCode

from app.api import websocket as websocket_module
from app.api.deps import get_temporal_client
from app.api.main import app
from app.orchestrator.constants import TASK_QUEUE
from app.shared.schemas_generated.concept_input_schema import ConceptInput
from app.shared.schemas_generated.progress_event_schema import ProgressEvent
from tests.temporal_fakes import description, pending_activity

VALID_INPUT = {"site": {"name": "Giza", "lat": 30.0, "lng": 31.2}}

# One scripted poll tick: what query() returns plus the run_phase heartbeat
# that describe() reports, or an exception that query() raises.
Tick = tuple[dict[str, str], dict[str, Any] | None] | Exception


def tick(status: str, step: str = "running", heartbeat: dict[str, Any] | None = None) -> Tick:
    return ({"current_phase": "research", "status": status, "step": step}, heartbeat)


def rpc_error(status: RPCStatusCode) -> RPCError:
    return RPCError(status.name, status, b"")


class FakeWorkflowHandle:
    """Plays back a scripted sequence of ticks; the last tick repeats forever."""

    def __init__(self, ticks: list[Tick]) -> None:
        self.ticks = ticks
        self.query_count = 0
        self.current: Tick | None = None

    async def query(self, name: str, *args: Any, **kwargs: Any) -> dict[str, str]:
        assert name == "progress"
        self.current = self.ticks[min(self.query_count, len(self.ticks) - 1)]
        self.query_count += 1
        if isinstance(self.current, Exception):
            raise self.current
        return self.current[0]

    async def describe(self) -> Any:
        assert isinstance(self.current, tuple)
        heartbeat = self.current[1]
        if heartbeat is None:
            return description()
        return description(await pending_activity("run_phase", heartbeat))


class FakeTemporalClient:
    """Stands in for temporalio.client.Client and records the calls the API makes."""

    data_converter = DataConverter.default

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.error: Exception | None = None
        self.handle = FakeWorkflowHandle([tick("running")])
        self.handle_ids: list[str] = []

    async def start_workflow(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error

    def get_workflow_handle(self, workflow_id: str) -> FakeWorkflowHandle:
        self.handle_ids.append(workflow_id)
        return self.handle


@pytest.fixture
def fake_client() -> Iterator[FakeTemporalClient]:
    fake = FakeTemporalClient()
    app.dependency_overrides[get_temporal_client] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    # Poll every 10 ms instead of 1.5 s so the tests run fast.
    monkeypatch.setattr(websocket_module, "POLL_SECONDS", 0.01)


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


# --- WS /ws/concept/{concept_id} ------------------------------------------


def test_websocket_sends_only_changes_then_closes_when_done(
    client: TestClient, fake_client: FakeTemporalClient
) -> None:
    fake_client.handle = FakeWorkflowHandle([tick("running"), tick("running"), tick("done")])

    with client.websocket_connect("/ws/concept/c_test") as websocket:
        first = websocket.receive_json()
        second = websocket.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()

    assert fake_client.handle_ids == ["c_test"]
    assert first["status"] == "running"
    assert second["status"] == "done"  # the duplicate "running" was not sent
    assert closed.value.code == 1000
    for event in (first, second):
        assert event["concept_id"] == "c_test"
        ProgressEvent.model_validate(event)


def test_websocket_event_carries_heartbeat_step_and_percent(
    client: TestClient, fake_client: FakeTemporalClient
) -> None:
    fake_client.handle = FakeWorkflowHandle(
        [
            tick("running", heartbeat={"step": "market_research", "percent": 25}),
            tick("running", heartbeat={"step": "gaps", "percent": 100}),
            tick("done", step="completed"),
        ]
    )

    with client.websocket_connect("/ws/concept/c_test") as websocket:
        events = [websocket.receive_json() for _ in range(3)]

    assert [(e["step"], e["percent"]) for e in events] == [
        ("market_research", 25),
        ("gaps", 100),
        ("completed", None),
    ]


def test_websocket_unknown_concept_sends_error_and_closes_4404(
    client: TestClient, fake_client: FakeTemporalClient
) -> None:
    fake_client.handle = FakeWorkflowHandle([rpc_error(RPCStatusCode.NOT_FOUND)])

    with client.websocket_connect("/ws/concept/c_missing") as websocket:
        event = websocket.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()

    ProgressEvent.model_validate(event)
    assert event["status"] == "failed"
    assert event["phase"] == "research"
    assert event["step"] == "not_found"
    assert event["message"] == "Unknown concept id"
    assert closed.value.code == 4404


def test_websocket_closes_1013_after_three_temporal_failures(
    client: TestClient, fake_client: FakeTemporalClient
) -> None:
    fake_client.handle = FakeWorkflowHandle([rpc_error(RPCStatusCode.UNAVAILABLE)])

    with client.websocket_connect("/ws/concept/c_test") as websocket:
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()  # no "failed" event: the run itself didn't fail

    assert closed.value.code == 1013
    assert fake_client.handle.query_count == 3


def test_websocket_recovers_from_brief_temporal_failures(
    client: TestClient, fake_client: FakeTemporalClient
) -> None:
    # Two failures, success (resets the counter), two more failures, success:
    # never three in a row, so the socket stays open until the run is done.
    fake_client.handle = FakeWorkflowHandle(
        [
            rpc_error(RPCStatusCode.UNAVAILABLE),
            rpc_error(RPCStatusCode.DEADLINE_EXCEEDED),
            tick("running"),
            rpc_error(RPCStatusCode.UNAVAILABLE),
            rpc_error(RPCStatusCode.UNAVAILABLE),
            tick("done"),
        ]
    )

    with client.websocket_connect("/ws/concept/c_test") as websocket:
        first = websocket.receive_json()
        second = websocket.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()

    assert (first["status"], second["status"]) == ("running", "done")
    assert closed.value.code == 1000


class DisconnectingWebSocket:
    """A browser that reads the first event and then closes the tab."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed_by_server = False
        self._left = asyncio.Event()

    async def accept(self) -> None:
        pass

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)
        self._left.set()

    async def receive(self) -> dict[str, Any]:
        await self._left.wait()
        return {"type": "websocket.disconnect", "code": 1001}

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed_by_server = True


async def test_websocket_stops_polling_when_browser_disconnects(
    fake_client: FakeTemporalClient,
) -> None:
    # Called directly instead of through TestClient: TestClient cancels the
    # whole app when its `with` block ends, which would hide a poll loop that
    # never stops. Here the handler must notice the disconnect and return on
    # its own, or wait_for times out.
    fake_client.handle = FakeWorkflowHandle([tick("running")])  # stuck on running forever
    websocket = DisconnectingWebSocket()

    await asyncio.wait_for(
        websocket_module.concept_progress(cast(Any, websocket), "c_test", cast(Any, fake_client)),
        timeout=1,
    )

    count_after_disconnect = fake_client.handle.query_count
    await asyncio.sleep(0.1)  # ~10 poll intervals
    assert fake_client.handle.query_count == count_after_disconnect
    assert len(websocket.sent) == 1
    assert websocket.closed_by_server is False  # the browser left; nothing to close


# --- CORS ------------------------------------------------------------------


def test_cors_allows_configured_origin(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:4200"})

    assert response.headers.get("access-control-allow-origin") == "http://localhost:4200"


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "https://example.com"})

    assert "access-control-allow-origin" not in response.headers
