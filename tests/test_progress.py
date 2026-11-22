"""Unit tests for the pure progress logic in app/api/progress.py."""

from datetime import UTC, datetime, timedelta

from temporalio.converter import DataConverter

from app.api.progress import build_event, has_changed, latest_heartbeat
from app.shared.schemas_generated.progress_event_schema import PhaseStatus
from tests.temporal_fakes import description, pending_activity

QUERY = {"current_phase": "research", "status": "running", "step": "running"}


# --- build_event ----------------------------------------------------------


def test_build_event_uses_heartbeat_step_and_percent() -> None:
    event = build_event("c_1", QUERY, {"step": "market_research", "percent": 25})

    assert event.concept_id == "c_1"
    assert event.phase == "research"
    assert event.status == PhaseStatus.running
    assert event.step == "market_research"
    assert event.percent == 25


def test_build_event_without_heartbeat_falls_back_to_query() -> None:
    event = build_event("c_1", {**QUERY, "step": "saving"}, None)

    assert event.step == "saving"
    assert event.percent is None


# --- has_changed ----------------------------------------------------------


def test_has_changed_first_event() -> None:
    assert has_changed(None, build_event("c_1", QUERY, None)) is True


def test_has_changed_ignores_timestamp() -> None:
    previous = build_event("c_1", QUERY, None)
    current = previous.model_copy(update={"timestamp": datetime.now(UTC) + timedelta(seconds=5)})

    assert has_changed(previous, current) is False


def test_has_changed_detects_new_step() -> None:
    previous = build_event("c_1", QUERY, {"step": "market_research", "percent": 25})
    current = build_event("c_1", QUERY, {"step": "gaps", "percent": 100})

    assert has_changed(previous, current) is True


# --- latest_heartbeat (real protobufs) ------------------------------------


async def test_latest_heartbeat_decodes_run_phase_heartbeat() -> None:
    heartbeat = {"step": "market_research", "percent": 25}
    desc = description(await pending_activity("run_phase", heartbeat))

    assert await latest_heartbeat(desc, DataConverter.default) == heartbeat


async def test_latest_heartbeat_run_phase_not_heartbeated_yet() -> None:
    desc = description(await pending_activity("run_phase"))

    assert await latest_heartbeat(desc, DataConverter.default) is None


async def test_latest_heartbeat_ignores_save_phase_result() -> None:
    desc = description(await pending_activity("save_phase_result"))

    assert await latest_heartbeat(desc, DataConverter.default) is None


async def test_latest_heartbeat_nothing_pending() -> None:
    assert await latest_heartbeat(description(), DataConverter.default) is None
