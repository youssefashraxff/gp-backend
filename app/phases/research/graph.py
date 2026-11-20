from typing import Any, NotRequired, TypedDict
from langgraph.graph import END, START, StateGraph
from collections.abc import Callable
from app.shared.phase_contract import ProgressCallback
import asyncio


class ResearchState(TypedDict):
    concept_id:str
    inputs:dict[str,Any]
    # The research node adds this field after completing the simulated steps.
    output: NotRequired[dict[str,Any]]

def build_research_graph(on_progress: ProgressCallback | None = None):
    async def research_node(state: ResearchState) -> dict[str, Any]:
        # simulating four research steps, each taking half a second, and reporting progress if a callback is provided.
        steps = ("market_research", "segments", "competitors", "gaps")

        for completed, step in enumerate(steps, start=1):
            await asyncio.sleep(0.5)

            if on_progress is not None:
                percent = completed * 100 // len(steps) 
                on_progress(step, percent)

        return {
            "output": {
                "target_segments": [{"name": "Young families", "share": 0.4}],
                "competitors": [],
                "gaps": [],
                "site_constraints": {},
            }
        }

    graph_builder = StateGraph(ResearchState)
    graph_builder.add_node("research", research_node)
    graph_builder.add_edge(START, "research")
    graph_builder.add_edge("research", END)
    return graph_builder.compile()


research_graph = build_research_graph()