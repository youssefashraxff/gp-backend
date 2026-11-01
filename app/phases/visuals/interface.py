"""Phase 3 — Visuals. Starts after Brand & Design is done."""

from typing import Any

NAME = "visuals"

# Declared dependencies (example — finalize when the phase is designed).
READS: tuple[str, ...] = ("research.target_segments", "brand_design.style_direction")


async def run(concept_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError("Phase 3 starts after Phase 2 is finished.")
