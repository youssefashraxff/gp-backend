import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.orchestrator.constants import TASK_QUEUE
from app.orchestrator.workflows import ConceptWorkflow


# define an asyn test function
@pytest.mark.asyncio
async def test_concept_workflow():
    #to advance it's test clock instead of waiting
    async with await WorkflowEnvironment.start_time_skipping() as env:  
        calls = []

        @activity.defn(name="run_phase") #defines that the funtion below is an activity
        async def fake_run_phase(concept_id: str, phase: str, inputs: dict):
            calls.append(("run_phase", phase))

            return {
                "concept_id": concept_id,
                "phase": phase,
                "status": "done",
                "inputs": inputs,
            }
        
        @activity.defn(name="save_phase_result")
        async def fake_save_phase_result(result: dict):
            calls.append(("save_phase_result", result["phase"]))
            return True

        #start a worker to exectue
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ConceptWorkflow],
            activities=[fake_run_phase, fake_save_phase_result],
        ):
            handle = await env.client.start_workflow(
                ConceptWorkflow.run,
                args=["C001", {"location": "New Cairo"}],
                id="test-concept-workflow",
                task_queue=TASK_QUEUE,
            )
            
            await handle.result()  #to get a return value
            assert calls == [
                ("run_phase", "research"),
                ("save_phase_result", "research"),
            ] #to check that activity order is correct or not
            progress = await handle.query(ConceptWorkflow.progress)
            assert progress == {
                "current_phase": "research",
                "status": "done",
                "step": "completed",
            }