"""Phase 2 — Brand & Design. Starts after Research is done."""

from typing import Any

NAME = "brand_design"

# Declared dependencies (example — finalize when the phase is designed).
READS: tuple[str, ...] = ("research.target_segments", "research.gaps")


async def run(concept_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError("Phase 2 starts after Phase 1 is finished.")
