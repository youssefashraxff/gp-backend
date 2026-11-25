"""Gap analysis experiment (plan X3, spec section 6.3).

What to find out: which prompt and model turn the saved Site and Market outputs into gaps
that each cite evidence, with no tools. Runs on real saved outputs, so it doesn't wait for
those agents to be finished:

    site = load_latest_output("site_analysis", site_id)
    market = load_latest_output("market_research", site_id)

Run:  python -m experiments.gap_analysis.run --site all --prompt v1 --model <model>
"""

from typing import Any

from experiments.shared.runner import RunConfig, load_latest_output, load_prompt, main

AGENT = "gap_analysis"


def run(site: dict[str, Any], config: RunConfig) -> dict[str, Any]:
    prompt = load_prompt(AGENT, config.prompt_version)  # noqa: F841 (used once implemented)
    inputs = {  # noqa: F841 (used once implemented)
        "site_analysis": load_latest_output("site_analysis", site["site_id"]),
        "market_research": load_latest_output("market_research", site["site_id"]),
    }
    # TODO(owner): one structured LLM call over `inputs` using `prompt`.
    # Return the output shape described in experiments/shared/scoring.py.
    raise NotImplementedError("Write the gap analysis experiment here")


if __name__ == "__main__":
    main(AGENT, run)
