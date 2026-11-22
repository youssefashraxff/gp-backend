"""WS /ws/concept/{concept_id}: push a concept's progress to the browser.

The API never receives progress from the worker directly. Instead it polls
Temporal every POLL_SECONDS (query + describe), turns that into a
ProgressEvent, and sends it only when something changed. Polling keeps the
load on Temporal fixed and predictable, however often the agent heartbeats.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from app.api.deps import get_temporal_client
from app.api.progress import build_event, has_changed, latest_heartbeat
from app.shared.schemas_generated.progress_event_schema import (
    PhaseName,
    PhaseStatus,
    ProgressEvent,
)

router = APIRouter()

# How often we ask Temporal for progress. 1-2 s is plenty for a progress bar.
POLL_SECONDS = 1.5

# Once the run reaches one of these, nothing more will change: close the socket.
FINAL_STATUSES = {PhaseStatus.done, PhaseStatus.failed}

# Errors that mean "Temporal is briefly unreachable", worth retrying.
TRANSIENT_ERRORS = {RPCStatusCode.UNAVAILABLE, RPCStatusCode.DEADLINE_EXCEEDED}
MAX_CONSECUTIVE_FAILURES = 3

# Close codes. 4000-4999 are free for apps; 4404 mirrors HTTP 404.
# 1013 is the standard "try again later" code.
CLOSE_NOT_FOUND = 4404
CLOSE_TRY_AGAIN_LATER = 1013


@router.websocket("/ws/concept/{concept_id}")
async def concept_progress(
    websocket: WebSocket,
    concept_id: str,
    client: Annotated[Client, Depends(get_temporal_client)],
) -> None:
    await websocket.accept()

    # Two tasks side by side: one polls and sends, the other only watches for
    # the browser leaving. Without the second one, a closed tab would leave the
    # poll loop calling Temporal forever, because we only notice a disconnect
    # when we read from the socket, and the poll loop never reads.
    poll = asyncio.create_task(_send_progress(websocket, client, concept_id))
    disconnect = asyncio.create_task(_wait_for_disconnect(websocket))
    tasks = {poll, disconnect}

    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Whichever finished first, stop the other one and wait until it has
        # stopped. This runs in `finally` so the tasks are also stopped if this
        # handler is itself cancelled (e.g. server shutdown). asyncio.wait, not
        # gather: gather would hide that cancellation from the server.
        for task in tasks:
            task.cancel()
        await asyncio.wait(tasks)

    # If the poll loop ended (normally or with an error), call result() so an
    # unexpected exception is raised and logged instead of silently swallowed.
    if poll in done:
        poll.result()


async def _send_progress(websocket: WebSocket, client: Client, concept_id: str) -> None:
    handle = client.get_workflow_handle(concept_id)  # workflow id == concept id
    previous: ProgressEvent | None = None
    failures = 0

    while True:
        try:
            # Query by name: importing workflows.py here would pull LangGraph
            # into the API process.
            query = await handle.query("progress")
            description = await handle.describe()
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                # Nothing will ever exist under this id: tell the browser and stop.
                await _send_not_found(websocket, concept_id)
                return
            if error.status not in TRANSIENT_ERRORS:
                raise

            # Temporal is briefly unreachable. The run itself is probably fine
            # (only our view of it is missing), so retry a few times instead
            # of sending a "failed" event.
            failures += 1
            if failures >= MAX_CONSECUTIVE_FAILURES:
                await websocket.close(
                    code=CLOSE_TRY_AGAIN_LATER,
                    reason="Progress is temporarily unavailable",
                )
                return
            await asyncio.sleep(POLL_SECONDS)
            continue

        failures = 0  # count only failures in a row

        # Phase-level state comes from the query, in-phase detail from the heartbeat.
        heartbeat = await latest_heartbeat(description, client.data_converter)
        current = build_event(concept_id, query, heartbeat)

        # Skip duplicates: most ticks nothing has changed.
        if has_changed(previous, current):
            await websocket.send_json(current.model_dump(mode="json"))
            previous = current

        if current.status in FINAL_STATUSES:
            await websocket.close()
            return

        # asyncio.sleep, not time.sleep: time.sleep would freeze every other
        # connection served by this process.
        await asyncio.sleep(POLL_SECONDS)


async def _send_not_found(websocket: WebSocket, concept_id: str) -> None:
    event = ProgressEvent(
        concept_id=concept_id,
        phase=PhaseName.research,
        status=PhaseStatus.failed,
        step="not_found",
        percent=None,
        message="Unknown concept id",
        timestamp=datetime.now(UTC),
    )
    await websocket.send_json(event.model_dump(mode="json"))
    await websocket.close(code=CLOSE_NOT_FOUND)


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    # The browser doesn't send us anything; we read only to notice when it leaves.
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
