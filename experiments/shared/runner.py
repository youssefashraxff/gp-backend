"""Run one agent experiment on one test site, then save the output and log the result.

Every run is kept: its full output goes to `experiments/<agent>/runs/` (a new file each
time, never overwritten) and one row is appended to `experiments/<agent>/results.csv`.
That way old and new versions of a prompt, model or pattern can always be compared.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from experiments.shared.scoring import score_output

EXPERIMENTS_DIR = Path(__file__).resolve().parent.parent
TEST_SITES_DIR = EXPERIMENTS_DIR / "test_sites"

RESULTS_COLUMNS = [
    "run_at",
    "site_id",
    "prompt_version",
    "model",
    "tools",
    "pattern",
    "evidence_coverage",
    "facts",
    "facts_without_evidence",
    "escalations",
    "cost_usd",
    "output_file",
    "notes",
]


@dataclass
class RunConfig:
    """What this run tried. Change one of these at a time between runs."""

    agent: str
    prompt_version: str
    model: str
    tools: str = ""
    pattern: str = ""
    notes: str = ""


# An agent experiment: takes the test site and the config, returns its output as a dict.
AgentFn = Callable[[dict[str, Any], RunConfig], dict[str, Any]]


def load_site(site_id: str, sites_dir: Path = TEST_SITES_DIR) -> dict[str, Any]:
    path = sites_dir / f"{site_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"No test site '{site_id}' in {sites_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_prompt(agent: str, version: str, base_dir: Path = EXPERIMENTS_DIR) -> str:
    """Read `experiments/<agent>/prompts/<version>.md`."""
    path = base_dir / agent / "prompts" / f"{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"No prompt '{version}' for {agent} at {path}")
    return path.read_text(encoding="utf-8")


def load_latest_output(
    agent: str, site_id: str, base_dir: Path = EXPERIMENTS_DIR
) -> dict[str, Any]:
    """The newest saved output of another agent for this site.

    Gap analysis and the Supervisor use this to run on real outputs of earlier agents
    instead of waiting for those agents to be built.
    """
    runs = sorted((base_dir / agent / "runs").glob(f"*__{site_id}.json"))
    if not runs:
        raise FileNotFoundError(f"No saved {agent} output for site '{site_id}' yet")
    return json.loads(runs[-1].read_text(encoding="utf-8"))["output"]


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9.-]+", "-", text).strip("-") or "none"


def run_experiment(
    agent_fn: AgentFn,
    config: RunConfig,
    site_id: str,
    base_dir: Path = EXPERIMENTS_DIR,
    sites_dir: Path = TEST_SITES_DIR,
) -> Path:
    """Run the agent on one site, save everything, append a results row. Returns the run file."""
    site = load_site(site_id, sites_dir)
    output = agent_fn(site, config)
    score = score_output(output)

    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    agent_dir = base_dir / config.agent
    runs_dir = agent_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    # Time first, so sorting by name is sorting by time.
    run_file = (
        runs_dir / f"{stamp}__{_slug(config.prompt_version)}__{_slug(config.model)}__{site_id}.json"
    )
    run_file.write_text(
        json.dumps(
            {"config": asdict(config), "site_id": site_id, "score": score, "output": output},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    results = agent_dir / "results.csv"
    new_file = not results.exists() or results.stat().st_size == 0
    with results.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow(
            {
                "run_at": now.isoformat(timespec="seconds"),
                "site_id": site_id,
                "prompt_version": config.prompt_version,
                "model": config.model,
                "tools": config.tools,
                "pattern": config.pattern,
                "evidence_coverage": score["evidence_coverage"],
                "facts": score["facts"],
                "facts_without_evidence": score["facts_without_evidence"],
                "escalations": score["escalations"],
                "cost_usd": output.get("cost_usd", ""),
                "output_file": run_file.name,
                "notes": config.notes,
            }
        )
    return run_file


def main(agent: str, agent_fn: AgentFn) -> None:
    """Command line for an agent's `run.py`.

    python -m experiments.<agent>.run --site site_01 --prompt v1 --model <model> \
        [--tools "..."] [--pattern "..."] [--notes "..."]
    """
    parser = argparse.ArgumentParser(description=f"Run a {agent} experiment")
    parser.add_argument("--site", required=True, help="test site id, e.g. site_01 (or 'all')")
    parser.add_argument("--prompt", required=True, help="prompt version, e.g. v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tools", default="")
    parser.add_argument("--pattern", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    config = RunConfig(agent, args.prompt, args.model, args.tools, args.pattern, args.notes)
    sites = (
        sorted(p.stem for p in TEST_SITES_DIR.glob("site_*.json"))
        if args.site == "all"
        else [args.site]
    )
    for site_id in sites:
        path = run_experiment(agent_fn, config, site_id)
        print(f"{site_id}: saved {path.relative_to(EXPERIMENTS_DIR)}")
