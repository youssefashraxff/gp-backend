"""Market research experiment (plan X2, spec section 6.2).

What to find out: which Tavily queries find real market sources for the test sites and
business types, which model synthesizes them best, and whether the 6-tool-call limit is
enough. Also settle Q9 with the Gap owner: does this agent collect basic supply-side info
(what already exists in the area)?

Run:  python -m experiments.market_research.run --site all --prompt v1 --model <model>
"""

from typing import Any

from experiments.shared.runner import RunConfig, load_prompt, main

AGENT = "market_research"


def run(site: dict[str, Any], config: RunConfig) -> dict[str, Any]:
    prompt = load_prompt(AGENT, config.prompt_version)  # noqa: F841 (used once implemented)
    # TODO(owner): search, then synthesize with the model using `prompt`.
    # Return the output shape described in experiments/shared/scoring.py.
    raise NotImplementedError("Write the market research experiment here")


if __name__ == "__main__":
    main(AGENT, run)
