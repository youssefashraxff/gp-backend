"""Supervisor experiment (plan X6, spec section 6.6).

What to find out: whether a single strong reviewer catches the problems in the saved
outputs of the other five agents (missing evidence, contradictions, uncovered business
types), and whether a critic or debate catches more for the extra cost. Try planting a
known problem in a copy of an output to see if it is caught.

Run:  python -m experiments.supervisor.run --site all --prompt v1 --model <model>
"""

from typing import Any

from experiments.shared.runner import RunConfig, load_latest_output, load_prompt, main

AGENT = "supervisor"
REVIEWED = ["site_analysis", "market_research", "gap_analysis", "segments", "competitors"]


def run(site: dict[str, Any], config: RunConfig) -> dict[str, Any]:
    prompt = load_prompt(AGENT, config.prompt_version)  # noqa: F841 (used once implemented)
    state = {a: load_latest_output(a, site["site_id"]) for a in REVIEWED}  # noqa: F841
    # TODO(owner): deterministic checks first, then the LLM review using `prompt`.
    # Return the output shape described in experiments/shared/scoring.py, plus "review".
    raise NotImplementedError("Write the supervisor experiment here")


if __name__ == "__main__":
    main(AGENT, run)
