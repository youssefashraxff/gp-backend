"""Tests for the web search comparison (experiments/tools/web_search). No network: the tool
function is replaced by a fake, and all files go to a temporary folder."""

import csv
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from experiments.tools.web_search import compare
from experiments.tools.web_search.compare import Result

REAL_DIR = Path(compare.__file__).resolve().parent


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    """A copy of the real inputs (queries, domains, settings) with empty runs/ and CSV."""
    for name in ("queries.json", "egypt_domains.txt"):
        shutil.copy(REAL_DIR / name, tmp_path / name)
    shutil.copytree(REAL_DIR / "settings", tmp_path / "settings")
    return tmp_path


def _fake_results() -> list[Result]:
    return [
        Result("https://www.youm7.com/story/1", "a", "...", "2026-03-01", 0.9),  # listed, dated
        Result("https://gafi.gov.eg/page", "b", "...", None, 0.8),  # ends in .eg
        Result("https://news.example.com/x", "c", "...", None, 0.7),
        Result("https://example.com/y", "d", "...", None, None),
    ]


def _fake_tool(query: str, settings: dict[str, Any]) -> tuple[Any, list[Result]]:
    return {"query": query, "results": ["raw"]}, _fake_results()


def _failing_tool(query: str, settings: dict[str, Any]) -> tuple[Any, list[Result]]:
    raise TimeoutError("took too long")


def _rows(base_dir: Path) -> list[dict[str, str]]:
    with (base_dir / "results.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_run_file_saved_and_never_overwritten(base_dir: Path, monkeypatch):
    monkeypatch.setitem(compare.TOOLS, "fake", _fake_tool)
    (base_dir / "settings" / "fake_v1.json").write_text("{}")

    compare.compare("fake", "v1", runs=1, query="sokhna_q1", base_dir=base_dir, pause=0)

    files = list((base_dir / "runs").glob("*.json"))
    assert len(files) == 1
    assert files[0].name.endswith("__fake__v1__sokhna_q1__run1.json")
    saved = json.loads(files[0].read_text())
    assert saved["query"]["id"] == "sokhna_q1"
    assert saved["raw_response"] == {"query": saved["query"]["query"], "results": ["raw"]}
    assert saved["run"] == 1 and saved["settings_version"] == "v1"

    with pytest.raises(FileExistsError):
        compare.save_run(base_dir / "runs", files[0].name, {"other": True})
    assert json.loads(files[0].read_text()) == saved


def test_row_counts_for_fake_response(base_dir: Path, monkeypatch):
    monkeypatch.setitem(compare.TOOLS, "fake", _fake_tool)
    (base_dir / "settings" / "fake_v1.json").write_text("{}")

    compare.compare("fake", "v1", runs=2, query="obour_q3", notes="n", base_dir=base_dir, pause=0)

    rows = _rows(base_dir)
    assert len(rows) == 2
    row = rows[0]
    assert row["n_results"] == "4"
    assert row["n_egyptian"] == "2"
    assert row["n_with_date"] == "1"
    assert row["n_unique_domains"] == "4"
    assert row["top3_urls"].count(" | ") == 2
    assert row["site"] == "new_obour" and row["group"] == "prices"
    assert row["error"] == "" and row["relevant"] == "" and row["notes"] == "n"
    assert [r["run"] for r in rows] == ["1", "2"]


def test_error_is_recorded_not_raised(base_dir: Path, monkeypatch):
    monkeypatch.setitem(compare.TOOLS, "broken", _failing_tool)
    (base_dir / "settings" / "broken_v1.json").write_text("{}")

    rows = compare.compare("broken", "v1", runs=2, query="sokhna_q2", base_dir=base_dir, pause=0)

    csv_rows = _rows(base_dir)
    assert len(csv_rows) == 2
    assert csv_rows[0]["error"] == "TimeoutError: took too long"
    assert csv_rows[0]["n_results"] == "0"
    assert len(list((base_dir / "runs").glob("*.json"))) == 2
    assert compare.summarize(rows) == ["sokhna_q2: all 2 runs failed"]


def test_summary_top3_stability_ignores_order():
    base = {"error": "", "n_results": 3, "n_egyptian": 1}
    rows = [
        {**base, "query_id": "q", "top3_urls": "a | b | c"},
        {**base, "query_id": "q", "top3_urls": "c | a | b"},
        {**base, "query_id": "q", "top3_urls": "a | b | d"},
    ]
    assert compare.summarize(rows) == ["q: avg results 3.0, avg Egyptian 1.0, top-3 stable 2/3"]
