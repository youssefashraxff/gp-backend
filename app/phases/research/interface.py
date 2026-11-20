"""Phase 1 — Research. The only entry point other code may import.

Inside this module [the research phase will include] (to be built): market research, then segment,
competitor/surroundings and gap analyses in parallel, site analysis,
and a supervisor that reviews and decides reruns — as a LangGraph.
"""

from typing import Any

from app.shared.phase_contract import ProgressCallback

from .graph import ResearchState, build_research_graph

NAME: str = "research"

# Research reads only the concept input, Research depends on zero output fields from earlier phases.
READS: tuple[str, ...] = ()


async def run(
    concept_id: str,
    inputs: dict[str, Any],
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the Research stub and return its output."""
    graph = build_research_graph(on_progress=on_progress)
    initial_state = ResearchState(concept_id=concept_id, inputs=inputs)
    result = await graph.ainvoke(initial_state)
    return result["output"]
