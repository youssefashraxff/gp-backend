"""Pure progress logic for the WebSocket: no network calls, so it is easy to test.

The WebSocket gets two views of a run from Temporal and merges them here:
- the workflow query  -> which phase, its status, and the coarse step;
- the describe result -> the latest heartbeat of the running activity,
  which has the fine-grained step and percent inside the phase.
"""

from datetime import UTC, datetime

from temporalio.client import WorkflowExecutionDescription
from temporalio.converter import DataConverter

from app.shared.schemas_generated.progress_event_schema import ProgressEvent

# Only this activity reports progress; save_phase_result never heartbeats.
PROGRESS_ACTIVITY = "run_phase"


def build_event(concept_id: str, query: dict, heartbeat: dict | None) -> ProgressEvent:
    """Combine the workflow query and the latest heartbeat into one ProgressEvent."""
    if heartbeat:
        step = heartbeat["step"]
        percent = heartbeat["percent"]
    else:
        step = query["step"]
        percent = None

    return ProgressEvent(
        concept_id=concept_id,
        phase=query["current_phase"],
        status=query["status"],
        step=step,
        percent=percent,
        timestamp=datetime.now(UTC),
    )


def has_changed(previous: ProgressEvent | None, current: ProgressEvent) -> bool:
    """True if `current` is worth sending: first event, or anything but the timestamp differs."""
    if previous is None:
        return True
    return previous.model_dump(exclude={"timestamp"}) != current.model_dump(exclude={"timestamp"})


async def latest_heartbeat(
    description: WorkflowExecutionDescription, converter: DataConverter
) -> dict | None:
    """Return the decoded {step, percent} of the running phase, or None if there is none."""
    for activity in description.raw_description.pending_activities:
        if activity.activity_type.name != PROGRESS_ACTIVITY:
            continue
        if not activity.HasField("heartbeat_details"):
            return None  # started, but no heartbeat sent yet
        details = await converter.decode(activity.heartbeat_details.payloads)
        return details[0] if details else None
    return None
