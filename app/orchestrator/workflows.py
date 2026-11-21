"""Temporal workflows: the flow *between* phases.

Owns: phase order, approval waits between phases, retries/timeouts,
waiting for the expert's answer during a mid-phase escalation (then
resuming from the LangGraph checkpoint), and rerunning stale phases.

Does NOT own anything inside a phase — that is LangGraph, behind each
phase's interface.py.

Phase order (a phase starts only after the previous one is done):
"""

from datetime import timedelta  # for timeouts

from temporalio import workflow
from temporalio.common import RetryPolicy  # for return policy

with workflow.unsafe.imports_passed_through():  # making sure no heavy imports
    from app.orchestrator.activities import run_phase, save_phase_result

PHASE_ORDER: tuple[str, ...] = ("research", "brand_design", "visuals", "investment")


# defining that this class will be a workflow
@workflow.defn
class ConceptWorkflow:
    def __init__(self):
        self.current_phase = None
        self.status = "starting"
        self.step = "starting"

    @workflow.run  # entry point for the workflow
    async def run(self, concept_id: str, inputs: dict):
        self.status = "running"
        self.step = "starting"
        try:
            for phase in PHASE_ORDER:  # hena for changing each phase
                self.current_phase = phase
                self.step = "running"
                # executing the run_phase activity
                result = await workflow.execute_activity(
                    run_phase,
                    args=[concept_id, phase, inputs],
                    # 10 3shan fi ai model and research not too short and not too long
                    start_to_close_timeout=timedelta(minutes=10),
                    # ye3mel singal eno lesa sha8al
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(
                        # yegrab kol ad eh
                        initial_interval=timedelta(seconds=3),
                        maximum_interval=timedelta(seconds=15),
                        maximum_attempts=3,
                    ),
                )
                await workflow.execute_activity(
                    save_phase_result,
                    args=[result],
                    # waiting for confirmation
                    start_to_close_timeout=timedelta(minutes=2),
                    # check after 1 min
                    heartbeat_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=3),
                        maximum_interval=timedelta(seconds=15),
                        maximum_attempts=3,
                    ),
                )
                if phase == "research":  # STOP after research for this sprint only
                    break
            # mark workflow as finished
            self.status = "done"
            self.step = "completed"

        except Exception:
            self.status = "failed"
            self.step = "failed"
            raise

    @workflow.query
    def progress(self) -> dict:
        return {
            "current_phase": self.current_phase,
            "status": self.status,
            "step": self.step,
        }
