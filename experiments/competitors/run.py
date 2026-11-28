"""Competitors experiment (plan X5, spec section 6.5).

What to find out: whether the density-based radius gives sensible areas on the test sites
(dense street vs new city vs desert road), how good Places results are for each business
type, and whether the cheap model classifies them correctly.

Run:  python -m experiments.competitors.run --site all --prompt v1 --model <model>
"""

from typing import Any

from experiments.shared.runner import RunConfig, load_prompt, main

AGENT = "competitors"


def run(site: dict[str, Any], config: RunConfig) -> dict[str, Any]:
    prompt = load_prompt(AGENT, config.prompt_version)  # noqa: F841 (used once implemented)
    # TODO(owner): radius -> Places search -> details -> classify -> summarize.
    # Return the output shape described in experiments/shared/scoring.py.
    raise NotImplementedError("Write the competitors experiment here")


if __name__ == "__main__":
    main(AGENT, run)
