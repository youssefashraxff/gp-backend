"""Worker process entry point.

Run locally:  python -m app.worker.main

Sprint 0: connect to Temporal (TEMPORAL_ADDRESS), register the ConceptWorkflow
from app.orchestrator and one activity per phase, each calling that phase's
interface.run(). The worker is the only process that runs agents.
"""


def main() -> None:
    raise NotImplementedError("Worker is built in Sprint 0 — see the ClickUp Sprint 0 list.")


if __name__ == "__main__":
    main()
