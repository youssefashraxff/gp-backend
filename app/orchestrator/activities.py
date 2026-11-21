from temporalio import activity

from app.orchestrator.phase_registry import PHASE_REGISTRY
from app.shared.hashing import content_hash
from app.shared.schemas_generated.phase_result_schema import (
    FieldValue,
    PhaseName,
    PhaseResult,
    PhaseStatus,
)


# function for running a phase and returning it's result(Worker task fills in its body)
# for now fake data
@activity.defn
async def run_phase(concept_id: str, phase: str, inputs: dict):
    # records a message inside an activity
    activity.logger.info(f"Running phase {phase} for concept {concept_id}")
    phase_interface = PHASE_REGISTRY[phase]

    def report_progress(step: str, percent: int) -> None:
        activity.heartbeat({"step": step, "percent": percent})

    output = await phase_interface.run(
        concept_id,
        inputs,
        on_progress=report_progress,
    )
    fields: dict[str, FieldValue] = {}

    for field_name, value in output.items():
        fields[field_name] = FieldValue(
            value=value,
            content_hash=content_hash(value),
        )

    result = PhaseResult(
        concept_id=concept_id,
        phase=PhaseName(phase),
        version=1,
        status=PhaseStatus.done,
        built_from=[],
        fields=fields,
    )

    return result.model_dump(mode="json")


# function to save result (Supabase task fills in its body)
@activity.defn
async def save_phase_result(result: dict):

    activity.logger.info(f"Saving result for concept {result['concept_id']}")

    return True
