"""Worker process entry point.

Run locally:  python -m app.worker.main

The worker polls Temporal for concept workflows and their activities.
"""

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from app.orchestrator.activities import run_phase, save_phase_result
from app.orchestrator.constants import TASK_QUEUE
from app.orchestrator.workflows import ConceptWorkflow
from app.shared.settings import settings


def main() -> None:
    asyncio.run(run_worker())


async def run_worker() -> None:
    # sends server address and namespace to Temporal server, then starts polling for tasks
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[ConceptWorkflow],
        activities=[run_phase, save_phase_result],
    )
    await worker.run()


if __name__ == "__main__":
    main()
