"""Tests for experiments/tools/web_search/score.py. Only local files: fake run files and
small source lists in a temporary folder."""

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from experiments.tools.web_search import score

EGYPT_CSV = """domain,name,source_type,egyptian,where_from
ahram.org.eg,Al-Ahram,news,yes,research
capmas.gov.eg,CAPMAS,official,yes,research
nawy.com,Nawy,listing_portal,yes,research
ouda-developments.com,Ouda,developer_broker,yes,runs
invest-gate.me,Invest-Gate,business_news,yes,runs
"""
INTL_CSV = """domain,name,source_type,egyptian,where_from,use_for
savills.com,Savills,consultancy_report,no,research,x
facebook.com,Facebook,social,no,runs,x
mordorintelligence.com,Mordor,paid_report,no,runs,x
tavily.com,Tavily,ignore,no,runs,ignore
"""


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    (tmp_path / "egypt_sources.csv").write_text(EGYPT_CSV)
    (tmp_path / "international_sources.csv").write_text(INTL_CSV)
    (tmp_path / "runs").mkdir()
    return tmp_path


def _write_run(base_dir: Path, name: str, urls: list[str], **extra: Any) -> None:
    run = {
        "timestamp": "2026-11-27T18:56:01+00:00",
        "tool": "tavily",
        "settings_version": "v1",
        "query_version": "v1",
        "query": {"id": "sokhna_q1", "site": "ain_sokhna", "group": "prices", "query": "q"},
        "run": 1,
        "seconds": 1.5,
        "error": None,
        "normalized": [
            {"url": u, "title": "", "snippet": "", "published_date": None, "score": None}
            for u in urls
        ],
        **extra,
    }
    (base_dir / "runs" / name).write_text(json.dumps(run))


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_domain_matching():
    ahram = score.Source("news", True)
    savills = score.Source("consultancy_report", False)
    savills_eg = score.Source("consultancy_report", True)
    sources = {"ahram.org.eg": ahram, "savills.com": savills, "savills.com.eg": savills_eg}

    # Lowercase, strip www., match by suffix.
    assert score.classify("https://www.Ahram.org.eg/x", sources) == ("ahram.org.eg", ahram)
    assert score.classify("https://english.ahram.org.eg/x", sources) == (
        "english.ahram.org.eg",
        ahram,
    )
    # Suffix means whole labels: savills.com.eg and savills.com don't match each other.
    assert score.classify("https://savills.com.eg/r", sources)[1] == savills_eg
    assert score.classify("https://www.savills.com/r", sources)[1] == savills
    assert score.classify("https://notsavills.com/r", sources)[1] is None
    # An unlisted .eg domain is Egyptian with type unlisted_eg.
    assert score.classify("https://shary.eg/p", sources)[1] == score.Source(score.UNLISTED_EG, True)


def test_real_source_lists_load():
    sources = score.load_sources()
    assert sources["ahram.org.eg"] == score.Source("news", True)
    assert sources["tavily.com"].source_type == score.IGNORE


def test_scores_row_counts(base_dir: Path):
    _write_run(
        base_dir,
        "20261127T185601000000__tavily__v1__sokhna_q1__run1.json",
        [
            "https://tavily.com/x",  # ignore: dropped from every count and from top 3
            "https://www.ouda-developments.com/a",  # developer, Egyptian
            "https://english.ahram.org.eg/b",  # news via suffix, Egyptian
            "https://capmas.gov.eg/c",  # official, Egyptian
            "https://invest-gate.me/d",  # business_news -> n_news
            "https://www.facebook.com/e",  # social
            "https://mordorintelligence.com/f",  # paid report
            "https://savills.com/g",  # consultancy -> n_report
            "https://nawy.com/h",  # listing
            "https://shary.eg/i",  # unlisted_eg: Egyptian + unlisted
            "https://random.example.com/j",  # unlisted
        ],
    )
    score.score_all(base_dir)
    [row] = _read(base_dir / "scores.csv")
    expected = {
        "status": "ok",
        "n_results": "10",
        "n_egyptian": "6",
        "n_official": "1",
        "n_news": "2",
        "n_report": "1",
        "n_listing": "1",
        "n_developer": "1",
        "n_social": "1",
        "n_paid_report": "1",
        "n_unlisted": "2",
        "n_with_date": "0",
        "unlisted_domains": "random.example.com; shary.eg",
    }
    assert {k: row[k] for k in expected} == expected
    assert row["top3_urls"].split(" | ")[0] == "https://www.ouda-developments.com/a"
    assert list(row) == score.SCORES_COLUMNS


def test_status_for_old_files_and_errors(base_dir: Path):
    _write_run(base_dir, "20261127T000001000000__tavily__v1__sokhna_q1__run1.json", [])
    _write_run(
        base_dir, "20261127T000002000000__tavily__v1__sokhna_q1__run2.json", [], error="Boom"
    )
    _write_run(
        base_dir,
        "20261127T000003000000__tavily__v1__sokhna_q1__run3.json",
        ["https://nawy.com/a"],
        status="ok",
    )
    score.score_all(base_dir)
    assert [r["status"] for r in _read(base_dir / "scores.csv")] == ["empty", "error", "ok"]
    [summary] = _read(base_dir / "summary.csv")
    assert (summary["runs"], summary["ok"], summary["empty"], summary["errors"]) == (
        "3",
        "1",
        "1",
        "1",
    )
    assert summary["avg_n_results"] == "0.5"  # over the 2 runs that didn't error


def test_summary_same_top3_ignores_order():
    base = {
        "tool": "t",
        "settings": "v1",
        "query_version": "v1",
        "query_id": "q",
        "site": "s",
        "group": "g",
        "status": "ok",
        "seconds": 1.0,
        **dict.fromkeys(score.COUNT_COLUMNS, 3),
    }
    rows = [
        {**base, "top3_urls": "a | b | c"},
        {**base, "top3_urls": "c | a | b"},
        {**base, "top3_urls": "a | b | d"},
    ]
    [summary] = score.summarize(rows)
    assert summary["same_top3"] == 2 and summary["avg_n_results"] == 3.0


def test_regenerating_keeps_manual_entries(base_dir: Path):
    first = "20261127T000001000000__tavily__v1__sokhna_q1__run1.json"
    _write_run(base_dir, first, ["https://nawy.com/a"], notes="baseline")
    score.score_all(base_dir)
    [row] = _read(base_dir / "manual.csv")
    assert row["run_file"] == first and row["notes"] == "baseline" and row["relevant"] == ""

    # Fill in by hand, add a new run, rescore twice: the hand entry survives.
    manual = base_dir / "manual.csv"
    manual.write_text(manual.read_text().replace(",,baseline", ",1,checked by hand"))
    second = "20261127T000002000000__tavily__v1__sokhna_q1__run2.json"
    _write_run(base_dir, second, ["https://nawy.com/b"])
    score.score_all(base_dir)
    score.score_all(base_dir)

    rows = _read(manual)
    assert [r["run_file"] for r in rows] == [first, second]
    assert (rows[0]["relevant"], rows[0]["notes"]) == ("1", "checked by hand")
    assert len(_read(base_dir / "scores.csv")) == 2  # regenerated, not appended


def test_finds_runs_in_tool_and_settings_folders(base_dir: Path):
    for version, stamp in (("v1", "000001"), ("v2", "000002")):
        folder = base_dir / "runs" / "tavily" / version
        folder.mkdir(parents=True)
        name = f"20261127T{stamp}000000__tavily__{version}__sokhna_q1__run1.json"
        _write_run(base_dir, name, ["https://nawy.com/a"], settings_version=version)
        (base_dir / "runs" / name).rename(folder / name)
    score.score_all(base_dir)
    assert [r["settings"] for r in _read(base_dir / "scores.csv")] == ["v1", "v2"]
    assert [r["settings"] for r in _read(base_dir / "summary.csv")] == ["v1", "v2"]


def test_query_versions_are_scored_separately(base_dir: Path):
    for version, stamp in (("v1", "000001"), ("v2", "000002")):
        name = f"20261127T{stamp}000000__tavily__v1__q{version}__sokhna_q1__run1.json"
        _write_run(base_dir, name, ["https://nawy.com/a"], query_version=version)
    score.score_all(base_dir)
    assert [r["query_version"] for r in _read(base_dir / "scores.csv")] == ["v1", "v2"]
    assert [r["query_version"] for r in _read(base_dir / "summary.csv")] == ["v1", "v2"]
