import os
from typing import Any, cast

from postgrest.exceptions import APIError

from app.shared.schemas_generated.concept_schema import Concept, ConceptInput, ConceptStatus
from app.shared.schemas_generated.phase_result_schema import (
    FieldRef,
    FieldValue,
    PhaseName,
    PhaseResult,
    PhaseStatus,
)
from supabase import Client, create_client

UNIQUE_VIOLATION = "23505"  # Postgres error code for a unique-constraint violation
MAX_SAVE_ATTEMPTS = 3

_client: Client | None = None


class ConceptNotFoundError(Exception):
    pass


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set (see .env.example)."
            )
        _client = create_client(url, key)
    return _client


def _row_to_concept(row: dict[str, Any]) -> Concept:
    # The table's `id` is `concept_id` in the schema; `updated_at` is database-only.
    return Concept(
        concept_id=row["id"],
        input=row["input"],
        status=row["status"],
        current_phase=row["current_phase"],
        created_at=row["created_at"],
    )


def _row_to_phase_result(row: dict[str, Any]) -> PhaseResult:
    # The internal `id` isn't part of the schema, which forbids unknown fields.
    data = {k: v for k, v in row.items() if k != "id"}
    return PhaseResult(**data)


def create_concept(concept_id: str, concept_input: ConceptInput) -> Concept:
    response = (
        get_client()
        .table("concepts")
        .insert({
            "id": concept_id,
            "input": concept_input.model_dump(mode="json", exclude_none=True),
        })
        .execute()
    )
    if not response.data:
        raise RuntimeError("No data returned from concepts insert")
    row = cast(dict[str, Any], response.data[0])
    return _row_to_concept(row)


def update_concept_status(
    concept_id: str,
    status: ConceptStatus,
    current_phase: PhaseName | None = None,
) -> Concept:
    changes: dict[str, Any] = {"status": status.value}
    if current_phase is not None:
        changes["current_phase"] = current_phase.value

    response = (
        get_client()
        .table("concepts")
        .update(changes)
        .eq("id", concept_id)
        .execute()
    )
    if not response.data:
        raise ConceptNotFoundError(concept_id)
    row = cast(dict[str, Any], response.data[0])
    return _row_to_concept(row)


def _latest_version(concept_id: str, phase: PhaseName) -> int:
    response = (
        get_client()
        .table("phase_results")
        .select("version")
        .eq("concept_id", concept_id)
        .eq("phase", phase.value)
        .order("version", desc=True)
        .limit(1)
        .execute()
    )
    if response.data and isinstance(response.data, list) and len(response.data) > 0:
        row = cast(dict[str, Any], response.data[0])
        return int(row["version"])
    return 0


def save_phase_result(
    concept_id: str,
    phase: PhaseName,
    status: PhaseStatus,
    fields: dict[str, FieldValue],
    built_from: list[FieldRef],
) -> PhaseResult:
    # Known limitation: if Temporal retries the activity after a successful save,
    # an extra version is created.
    row: dict[str, Any] = {
        "concept_id": concept_id,
        "phase": phase.value,
        "status": status.value,
        "fields": {path: value.model_dump(mode="json") for path, value in fields.items()},
        "built_from": [ref.model_dump(mode="json") for ref in built_from],
    }

    for attempt in range(MAX_SAVE_ATTEMPTS):
        row["version"] = _latest_version(concept_id, phase) + 1
        try:
            response = get_client().table("phase_results").insert(row).execute()
            if not response.data:
                raise RuntimeError("No data returned from phase_results insert")
            res_row = cast(dict[str, Any], response.data[0])
            return _row_to_phase_result(res_row)
        except APIError as error:
            # A concurrent save took this version number: retry with the next one.
            if error.code != UNIQUE_VIOLATION or attempt == MAX_SAVE_ATTEMPTS - 1:
                raise

    raise RuntimeError("unreachable")


def get_latest_phase_result(concept_id: str, phase: PhaseName) -> PhaseResult | None:
    response = (
        get_client()
        .table("phase_results")
        .select("*")
        .eq("concept_id", concept_id)
        .eq("phase", phase.value)
        .order("version", desc=True)
        .limit(1)
        .execute()
    )
    if response.data and isinstance(response.data, list) and len(response.data) > 0:
        row = cast(dict[str, Any], response.data[0])
        return _row_to_phase_result(row)
    return None
