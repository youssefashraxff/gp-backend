"""The experiments runner keeps every run and scores outputs the same way."""

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from experiments.shared.runner import RunConfig, load_latest_output, run_experiment
from experiments.shared.scoring import score_output

GOOD_FACT = {
    "claim": "Ring road is 400 m away",
    "value": 400,
    "type": "computable",
    "evidence": {"source": "distance_to_road()", "retrieved_at": "2026-11-26T10:00:00Z"},
}


def fake_agent(site: dict[str, Any], config: RunConfig) -> dict[str, Any]:
    return {"facts": [GOOD_FACT], "escalations": [], "summary": site["name"], "cost_usd": 0.01}


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    sites = tmp_path / "test_sites"
    sites.mkdir()
    (sites / "site_01.json").write_text(json.dumps({"site_id": "site_01", "name": "Test"}))
    return tmp_path, sites


def test_every_run_is_kept_and_logged(dirs: tuple[Path, Path]) -> None:
    base, sites = dirs
    for version in ["v1", "v2"]:
        config = RunConfig("site_analysis", version, "model-a", notes=f"try {version}")
        run_experiment(fake_agent, config, "site_01", base_dir=base, sites_dir=sites)

    runs = sorted((base / "site_analysis" / "runs").glob("*.json"))
    assert len(runs) == 2  # the second run did not overwrite the first
    with (base / "site_analysis" / "results.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert [r["prompt_version"] for r in rows] == ["v1", "v2"]
    assert rows[0]["evidence_coverage"] == "1.0"
    assert rows[1]["output_file"] == runs[1].name


def test_load_latest_output_reads_the_newest_run(dirs: tuple[Path, Path]) -> None:
    base, sites = dirs
    run_experiment(fake_agent, RunConfig("market_research", "v1", "m"), "site_01", base, sites)
    assert load_latest_output("market_research", "site_01", base)["summary"] == "Test"
    with pytest.raises(FileNotFoundError):
        load_latest_output("market_research", "site_99", base)


def test_fact_without_source_lowers_coverage() -> None:
    bad = {"claim": "40% are students", "value": 0.4, "type": "retrieved", "evidence": {}}
    score = score_output({"facts": [GOOD_FACT, bad], "escalations": [{"question": "?"}]})
    assert score["facts_without_evidence"] == 1
    assert score["missing_evidence"] == ["40% are students"]
    assert score["evidence_coverage"] == 0.5
    assert score["escalations"] == 1


def test_unknown_fact_type_counts_as_missing_evidence() -> None:
    guessed = {**GOOD_FACT, "type": "estimated"}
    assert score_output({"facts": [guessed]})["evidence_coverage"] == 0.0
