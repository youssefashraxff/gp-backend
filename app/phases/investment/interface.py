"""Phase 4 — Investment. Starts after Visuals is done."""

from typing import Any

NAME = "investment"

# Declared dependencies (example — finalize when the phase is designed).
READS: tuple[str, ...] = ("research.site_constraints", "research.competitors")


async def run(concept_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError("Phase 4 starts after Phase 3 is finished.")
