from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket

from app.shared.schemas_generated.progress_event_schema import PhaseName, PhaseStatus, ProgressEvent

router = APIRouter()


@router.websocket("/ws/concept/{concept_id}")
async def event(websocket: WebSocket, concept_id: str):
    await websocket.accept()
    # Create the object to be converted to json
    event = ProgressEvent(
        concept_id=concept_id,
        phase=PhaseName.research,
        status=PhaseStatus.queued,
        step="waiting",
        timestamp=datetime.now(UTC),
        percent=None,
    )
    # Converting and sending
    await websocket.send_json(event.model_dump(mode="json"))
    await websocket.close()
