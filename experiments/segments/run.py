"""Segments experiment (plan X4, spec section 6.4).

What to find out: which sources give real demographic figures for the test sites (they are
often missing in Egypt), whether 5 tool calls are enough, and that the agent escalates
instead of estimating a share. Reads the saved Gap output:

    gaps = load_latest_output("gap_analysis", site_id)

Run:  python -m experiments.segments.run --site all --prompt v1 --model <model>
"""

from typing import Any

from experiments.shared.runner import RunConfig, load_prompt, main

AGENT = "segments"


def run(site: dict[str, Any], config: RunConfig) -> dict[str, Any]:
    prompt = load_prompt(AGENT, config.prompt_version)  # noqa: F841 (used once implemented)
    # TODO(owner): search for who lives/works near the site, match segments to gaps.
    # Return the output shape described in experiments/shared/scoring.py.
    raise NotImplementedError("Write the segments experiment here")


if __name__ == "__main__":
    main(AGENT, run)
