from temporalio import activity
#function for running a phase and returning it's result(Worker task fills in its body)
#for now fake data
@activity.defn
async def run_phase(concept_id: str, phase: str, inputs: dict): 
    # records a message inside an activity
    activity.logger.info(f"Running phase {phase} for concept {concept_id}")
    return {
        "concept_id": concept_id,
        "phase": phase,
        "status": "done",
        "inputs": inputs,
    }

#function to save result (Supabase task fills in its body)
@activity.defn
async def save_phase_result(result: dict):

    activity.logger.info(f"Saving result for concept {result['concept_id']}")

    return True