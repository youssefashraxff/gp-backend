import pytest
from temporalio.testing import ActivityEnvironment

from app.orchestrator.activities import run_phase
from app.shared.hashing import content_hash


@pytest.mark.asyncio
async def test_run_phase_reports_progress_and_returns_hashed_fields():
    env = ActivityEnvironment()
    heartbeats = []
    env.on_heartbeat = heartbeats.append

    result = await env.run(run_phase, "concept-1", "research", {})

    assert heartbeats == [
        {"step": "market_research", "percent": 25},
        {"step": "segments", "percent": 50},
        {"step": "competitors", "percent": 75},
        {"step": "gaps", "percent": 100},
    ]

    expected_output = {
        "target_segments": [{"name": "Young families", "share": 0.4}],
        "competitors": [],
        "gaps": [],
        "site_constraints": {},
    }

    assert result["concept_id"] == "concept-1"
    assert result["phase"] == "research"
    assert result["fields"] == {
        name: {"value": value, "content_hash": content_hash(value)}
        for name, value in expected_output.items()
    }