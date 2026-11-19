from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from temporalio.client import Client
from temporalio.service import RPCError

from app.api.deps import get_temporal_client
from app.orchestrator.constants import TASK_QUEUE
from app.shared.schemas_generated.concept_schema import (
    Concept,
    ConceptInput,
    ConceptStatus,
    PhaseName,
)

router = APIRouter()


@router.post("/concept", status_code=status.HTTP_202_ACCEPTED)
async def start_concept(
    concept_input: ConceptInput,
    client: Annotated[Client, Depends(get_temporal_client)],
) -> Concept:
    concept_id = f"c_{uuid4().hex}"

    try:
        await client.start_workflow(
            "ConceptWorkflow",
            args=[concept_id, concept_input.model_dump(mode="json")],
            id=concept_id,
            task_queue=TASK_QUEUE,
        )
    except RPCError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not start the concept. Please try again.",
        ) from error

    # saving into DB
    return Concept(
        concept_id=concept_id,
        input=concept_input,
        status=ConceptStatus.created,
        current_phase=PhaseName.research,
        created_at=datetime.now(UTC),
    )