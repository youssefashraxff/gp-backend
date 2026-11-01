"""Phase 1 — Research. The only entry point other code may import.

Inside this module (to be built): market research, then segment,
competitor/surroundings and gap analyses in parallel, site analysis,
and a supervisor that reviews and decides reruns — as a LangGraph.
"""

from typing import Any

NAME = "research"

# Research reads only the concept input, not earlier phases.
READS: tuple[str, ...] = ()


async def run(concept_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """Sprint 0 stub: returns fixed output shaped like the real result."""
    return {
        "target_segments": [{"name": "Young families", "share": 0.4}],
        "competitors": [],
        "gaps": [],
        "site_constraints": {},
    }
