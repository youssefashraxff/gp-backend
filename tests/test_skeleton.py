from fastapi.testclient import TestClient

from app.api.main import app
from app.phases.research import interface as research
from app.shared.hashing import content_hash


def test_health() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_hash_ignores_key_order() -> None:
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


def test_hash_changes_with_value() -> None:
    assert content_hash({"a": 1}) != content_hash({"a": 2})


async def test_research_stub_returns_fields() -> None:
    output = await research.run("c_test", {})
    assert "target_segments" in output
