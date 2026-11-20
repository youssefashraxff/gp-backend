import asyncio

from app.phases.research.graph import ResearchState, build_research_graph, research_graph


def test_research_graph_returns_expected_output():
    initial_state: ResearchState = {"concept_id": "concept-1", "inputs": {}}

    result = asyncio.run(research_graph.ainvoke(initial_state))

    assert result["output"] == {
        "target_segments": [{"name": "Young families", "share": 0.4}],
        "competitors": [],
        "gaps": [],
        "site_constraints": {},
    }


def test_research_graph_reports_progress():
    updates: list[tuple[str, int]] = []

    # define a callback function to record progress updates
    def record_progress(step: str, percent: int) -> None:
        updates.append((step, percent))

    graph = build_research_graph(on_progress=record_progress)
    initial_state = ResearchState(concept_id="concept-1", inputs={})

    asyncio.run(graph.ainvoke(initial_state))

    assert updates == [
        ("market_research", 25),
        ("segments", 50),
        ("competitors", 75),
        ("gaps", 100),
    ]
