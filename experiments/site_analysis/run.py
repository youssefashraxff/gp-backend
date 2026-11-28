"""Site analysis experiment (plan X1, spec section 6.1).

What to find out: whether OSM (Overpass) and Google Elevation give usable roads, access and
terrain around each test pin, and whether the cheap model writes a summary that cites only
those facts. Most of this agent is plain functions (distances, sun path), so data quality
matters more than the model here.

Run:  python -m experiments.site_analysis.run --site all --prompt v1 --model <model>
"""

from typing import Any

from experiments.shared.runner import RunConfig, load_prompt, main

AGENT = "site_analysis"


def run(site: dict[str, Any], config: RunConfig) -> dict[str, Any]:
    prompt = load_prompt(AGENT, config.prompt_version)  # noqa: F841 (used once implemented)
    # TODO(owner): call the tools, compute the facts, call the model with `prompt`.
    # Return the output shape described in experiments/shared/scoring.py.
    raise NotImplementedError("Write the site analysis experiment here")


if __name__ == "__main__":
    main(AGENT, run)
