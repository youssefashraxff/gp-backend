"""Tests for experiments/tools/web_search/compare.py. No network: the tool function is
replaced by a fake, and all files go to a temporary folder."""

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
    """A copy of the real inputs (queries, settings) with an empty runs/ folder."""
    shutil.copy(REAL_DIR / "queries.json", tmp_path / "queries.json")
    shutil.copytree(REAL_DIR / "settings", tmp_path / "settings")
    return tmp_path


def _register(monkeypatch, base_dir: Path, name: str, fn) -> None:
    monkeypatch.setitem(compare.TOOLS, name, fn)
    (base_dir / "settings" / f"{name}_v1.json").write_text("{}")


def _saved(base_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted((base_dir / "runs").rglob("*.json"))]


def _fake_tool(query: str, settings: dict[str, Any]) -> tuple[Any, list[Result]]:
    return {"query": query, "results": ["raw"]}, [Result("https://youm7.com/a", "t", "s")]


def test_default_runs_is_two(base_dir: Path, monkeypatch):
    _register(monkeypatch, base_dir, "fake", _fake_tool)
    compare.compare("fake", "v1", query="sokhna_q1", base_dir=base_dir, pause=0)
    assert [s["run"] for s in _saved(base_dir)] == [1, 2]


def test_run_file_saved_and_never_overwritten(base_dir: Path, monkeypatch):
    _register(monkeypatch, base_dir, "fake", _fake_tool)
    paths = compare.compare(
        "fake", "v1", runs=1, query="sokhna_q1", notes="n", base_dir=base_dir, pause=0
    )

    assert len(paths) == 1 and paths[0].name.endswith("__fake__v1__sokhna_q1__run1.json")
    assert paths[0].parent == base_dir / "runs" / "fake" / "v1"
    saved = json.loads(paths[0].read_text())
    assert saved["status"] == "ok" and saved["attempts"] == 1 and saved["notes"] == "n"
    assert saved["raw_response"] == {"query": saved["query"]["query"], "results": ["raw"]}
    assert saved["normalized"][0]["url"] == "https://youm7.com/a"
    assert "n_egyptian" not in saved  # compare.py no longer scores

    with pytest.raises(FileExistsError):
        compare.save_run(paths[0].parent, paths[0].name, {"other": True})
    assert json.loads(paths[0].read_text()) == saved


def test_error_is_saved_not_raised(base_dir: Path, monkeypatch):
    def broken(query: str, settings: dict[str, Any]) -> tuple[Any, list[Result]]:
        raise TimeoutError("took too long")

    _register(monkeypatch, base_dir, "broken", broken)
    compare.compare("broken", "v1", runs=2, query="sokhna_q2", base_dir=base_dir, pause=0)

    saved = _saved(base_dir)
    assert len(saved) == 2
    assert saved[0]["status"] == "error" and saved[0]["error"] == "TimeoutError: took too long"
    assert saved[0]["attempts"] == 1  # errors are not retried


def test_empty_is_retried_once_then_saved_as_empty(base_dir: Path, monkeypatch):
    calls = []

    def empty(query: str, settings: dict[str, Any]) -> tuple[Any, list[Result]]:
        calls.append(query)
        return {"results": []}, []

    _register(monkeypatch, base_dir, "empty", empty)
    compare.compare("empty", "v1", runs=1, query="obour_q1", base_dir=base_dir, pause=0)

    assert len(calls) == 2
    [saved] = _saved(base_dir)
    assert saved["status"] == "empty" and saved["attempts"] == 2


def test_empty_then_results_on_retry_is_ok(base_dir: Path, monkeypatch):
    answers = [[], [Result("https://nawy.com/x", "t", "s")]]

    def flaky(query: str, settings: dict[str, Any]) -> tuple[Any, list[Result]]:
        return {}, answers.pop(0)

    _register(monkeypatch, base_dir, "flaky", flaky)
    compare.compare("flaky", "v1", runs=1, query="obour_q1", base_dir=base_dir, pause=0)

    [saved] = _saved(base_dir)
    assert saved["status"] == "ok" and saved["attempts"] == 2 and len(saved["normalized"]) == 1
