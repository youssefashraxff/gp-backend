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
    for name in ("queries.json", "queries_v2.json"):
        shutil.copy(REAL_DIR / name, tmp_path / name)
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

    assert len(paths) == 1 and paths[0].name.endswith("__fake__v1__qv1__sokhna_q1__run1.json")
    assert paths[0].parent == base_dir / "runs" / "fake" / "v1" / "queries_v1"
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


def test_arabic_query_version(base_dir: Path, monkeypatch):
    seen = []

    def fake(query: str, settings: dict[str, Any]) -> tuple[Any, list[Result]]:
        seen.append(query)
        return {}, [Result("https://youm7.com/a", "t", "s")]

    _register(monkeypatch, base_dir, "fake", fake)
    [path] = compare.compare(
        "fake", "v1", runs=1, query="sokhna_q1", base_dir=base_dir, pause=0, query_version="v2"
    )

    assert seen == ["حجم سوق الفنادق والمطاعم في العين السخنة 2026"]
    assert path.parent == base_dir / "runs" / "fake" / "v1" / "queries_v2"
    assert "__qv2__sokhna_q1__" in path.name
    text = path.read_text(encoding="utf-8")
    assert "العين السخنة" in text  # saved as UTF-8, not \u escapes
    saved = json.loads(text)
    assert saved["query_version"] == "v2" and saved["query_language"] == "ar"


def test_default_query_version_is_v1_and_unknown_is_refused(base_dir: Path):
    assert compare.load_queries(base_dir=base_dir)["version"] == "v1"
    with pytest.raises(FileNotFoundError):
        compare.load_queries("v9", base_dir)
    (base_dir / "queries_v3.json").write_text('{"version": "v2", "queries": []}')
    with pytest.raises(ValueError):
        compare.load_queries("v3", base_dir)


# --- strategy ("mixed": several searches per question, one run file) ----------------------

STRATEGY = {
    "strategy": "mixed",
    "base": {"max_results": 10},
    "searches": [
        {
            "name": "ar_restricted",
            "queries": "v2",
            "include_domains_mode": "restrict",
            "include_domains": ["youm7.com"],
        },
        {
            "name": "en_restricted",
            "queries": "v1",
            "include_domains_mode": "restrict",
            "include_domains": ["reuters.com"],
        },
        {"name": "open", "queries": "v1"},
    ],
}


def _strategy_tool(answers: dict[str, list[Result] | Exception], calls: list[tuple[str, dict]]):
    """A fake tool that answers by search: Arabic text -> ar, restrict -> en, else open."""

    def tool(query: str, settings: dict[str, Any]) -> tuple[Any, list[Result]]:
        calls.append((query, settings))
        if settings.get("include_domains_mode") != "restrict":
            name = "open"
        elif "العين" in query:
            name = "ar_restricted"
        else:
            name = "en_restricted"
        answer = answers[name]
        if isinstance(answer, Exception):
            raise answer
        return {"from": name}, answer

    return tool


def _run_strategy(base_dir: Path, monkeypatch, answers) -> tuple[dict, list]:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setitem(compare.TOOLS, "fake", _strategy_tool(answers, calls))
    (base_dir / "settings" / "fake_v3.json").write_text(json.dumps(STRATEGY))
    [path] = compare.compare("fake", "v3", runs=1, query="sokhna_q1", base_dir=base_dir, pause=0)
    assert path.parent == base_dir / "runs" / "fake" / "v3" / "queries_v1+v2"
    return json.loads(path.read_text(encoding="utf-8")), calls


def test_strategy_saves_one_file_with_every_search_and_merged_results(base_dir, monkeypatch):
    answers = {
        "ar_restricted": [Result("https://youm7.com/a", "t", "s", None, 0.5)],
        "en_restricted": [],  # restricted and empty: normal, no retry
        "open": [
            Result("https://youm7.com/a/", "t", "s", "2026-01-01", 0.9),  # same URL as ar
            Result("https://nawy.com/b", "t", "s", None, 0.7),
        ],
    }
    saved, calls = _run_strategy(base_dir, monkeypatch, answers)

    assert len(calls) == 3  # one call per search, no retry for the empty restricted one
    ar_call, en_call, open_call = calls
    assert ar_call[0] == "حجم سوق الفنادق والمطاعم في العين السخنة 2026"
    assert ar_call[1] == {
        "max_results": 10,
        "include_domains_mode": "restrict",
        "include_domains": ["youm7.com"],
    }
    assert en_call[0] == open_call[0] == "Ain Sokhna hospitality F&B market size 2026"
    assert open_call[1] == {"max_results": 10}

    assert saved["strategy"] == "mixed" and saved["query_version"] == "v1+v2"
    assert saved["query"] == {"id": "sokhna_q1", "site": "ain_sokhna", "group": "market_division"}
    by_name = {s["name"]: s for s in saved["searches"]}
    assert list(by_name) == ["ar_restricted", "en_restricted", "open"]
    assert by_name["ar_restricted"]["raw_response"] == {"from": "ar_restricted"}
    assert by_name["en_restricted"]["status"] == "empty"
    assert by_name["en_restricted"]["attempts"] == 1
    assert by_name["open"]["status"] == "ok"

    # Merged: deduplicated by URL (trailing slash ignored), best score first, found_by kept.
    merged = saved["normalized"]
    assert [r["url"] for r in merged] == ["https://youm7.com/a", "https://nawy.com/b"]
    assert merged[0]["found_by"] == ["ar_restricted", "open"]
    assert merged[0]["score"] == 0.9 and merged[0]["published_date"] == "2026-01-01"
    assert merged[1]["found_by"] == ["open"]
    assert saved["status"] == "ok" and saved["error"] is None


def test_strategy_open_search_retries_when_empty(base_dir, monkeypatch):
    answers = {"ar_restricted": [], "en_restricted": [], "open": []}
    saved, calls = _run_strategy(base_dir, monkeypatch, answers)
    assert len(calls) == 4  # only the open search is retried
    assert [s["attempts"] for s in saved["searches"]] == [1, 1, 2]
    assert saved["status"] == "empty" and saved["normalized"] == []


def test_strategy_records_a_failing_search_and_keeps_the_others(base_dir, monkeypatch):
    answers = {
        "ar_restricted": TimeoutError("slow"),
        "en_restricted": [Result("https://reuters.com/x", "t", "s")],
        "open": [Result("https://nawy.com/b", "t", "s")],
    }
    saved, _ = _run_strategy(base_dir, monkeypatch, answers)
    assert saved["searches"][0]["status"] == "error"
    assert saved["status"] == "ok" and len(saved["normalized"]) == 2
    assert saved["error"] == "ar_restricted: TimeoutError: slow"


def test_real_v3_settings_are_within_tavily_limits():
    v3 = compare.load_settings("tavily", "v3")
    names = [s["name"] for s in v3["searches"]]
    assert names == ["ar_restricted", "en_restricted", "open"]
    for search in v3["searches"][:2]:
        assert search["include_domains_mode"] == "restrict"
        assert 0 < len(search["include_domains"]) <= 300
    assert "include_domains" not in v3["searches"][2]
    assert v3["base"] == compare.load_settings("tavily", "v1")


def test_real_v4_settings_differ_from_v3_only_in_the_domain_lists():
    v3, v4 = compare.load_settings("tavily", "v3"), compare.load_settings("tavily", "v4")
    assert v4["strategy"] == v3["strategy"] and v4["base"] == v3["base"]
    for a, b in zip(v3["searches"], v4["searches"], strict=True):
        assert {k: v for k, v in a.items() if k != "include_domains"} == {
            k: v for k, v in b.items() if k != "include_domains"
        }
    ar, en, _ = (set(s.get("include_domains", [])) for s in v4["searches"])
    assert 0 < len(ar) < len(v3["searches"][0]["include_domains"]) and not ar & en
