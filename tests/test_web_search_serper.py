"""Tests for the Serper tool in experiments/tools/web_search. No network: httpx.post is
replaced by a fake, and all files go to a temporary folder."""

import csv
import json
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest

from experiments.tools.web_search import compare, score

REAL_DIR = Path(compare.__file__).resolve().parent
FAKE_KEY = "test-serper-key-do-not-print"

ORGANIC = {
    "searchParameters": {"q": "x"},
    "answerBox": {"answer": "about 30 hotels"},
    "knowledgeGraph": {"title": "Ain Sokhna"},
    "peopleAlsoAsk": [{"question": "Is Ain Sokhna busy in summer?"}],
    "organic": [
        {
            "title": "A",
            "link": "https://www.youm7.com/story/1",
            "snippet": "s1",
            "date": "3 days ago",
            "position": 1,
        },
        {"title": "B", "link": "https://capmas.gov.eg/b", "snippet": "s2", "position": 2},
    ],
}


@pytest.fixture
def base_dir(tmp_path: Path, monkeypatch) -> Path:
    for name in (
        "queries.json",
        "queries_v2.json",
        "egypt_sources.csv",
        "international_sources.csv",
    ):
        shutil.copy(REAL_DIR / name, tmp_path / name)
    shutil.copytree(REAL_DIR / "settings", tmp_path / "settings")
    monkeypatch.setenv("SERPER_API_KEY", FAKE_KEY)
    return tmp_path


def _fake_post(monkeypatch, responses: list[Any]) -> list[dict[str, Any]]:
    """Replace httpx.post: each call pops the next response (or raises it)."""
    calls: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        answer = responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(compare.httpx, "post", post)
    return calls


def test_search_serper_sends_the_request_and_normalises(monkeypatch, base_dir):
    calls = _fake_post(monkeypatch, [(200, ORGANIC)])
    raw, results = compare.search_serper("q text", {"gl": "eg", "hl": "ar", "num": 10})

    [call] = calls
    assert call["url"] == "https://google.serper.dev/search"
    assert call["headers"]["X-API-KEY"] == FAKE_KEY
    assert call["json"] == {"q": "q text", "gl": "eg", "hl": "ar", "num": 10}
    assert raw == ORGANIC  # full response kept: answerBox, knowledgeGraph, peopleAlsoAsk
    first, second = results
    assert (first.url, first.title, first.snippet) == ("https://www.youm7.com/story/1", "A", "s1")
    assert first.published_date == "3 days ago" and second.published_date is None
    assert (first.position, first.score) == (1, 1.0)
    assert (second.position, second.score) == (2, 0.5)


def _run(base_dir: Path, monkeypatch, responses: list[Any]) -> tuple[dict, list]:
    calls = _fake_post(monkeypatch, responses)
    [path] = compare.compare("serper", "v1", runs=1, query="sokhna_q1", base_dir=base_dir, pause=0)
    assert path.parent == base_dir / "runs" / "serper" / "v1" / "queries_v1+v2"
    return json.loads(path.read_text(encoding="utf-8")), calls


def test_serper_v1_strategy_run(monkeypatch, base_dir):
    ar_body = {
        "organic": [
            {"title": "C", "link": "https://youm7.com/story/1/", "position": 1},  # same as en
            {"title": "D", "link": "https://nawy.com/x", "date": "Jan 5, 2026", "position": 2},
        ]
    }
    saved, calls = _run(base_dir, monkeypatch, [(200, ORGANIC), (200, ar_body)])

    en_call, ar_call = calls
    assert en_call["json"] == {
        "q": "Ain Sokhna hospitality F&B market size 2026",
        "gl": "eg",
        "hl": "en",
        "num": 10,
    }
    assert ar_call["json"]["q"] == "حجم سوق الفنادق والمطاعم في العين السخنة 2026"
    assert ar_call["json"]["hl"] == "ar"

    en, ar = saved["searches"]
    assert (en["name"], ar["name"]) == ("en_open", "ar_open")
    assert en["raw_response"]["answerBox"] == {"answer": "about 30 hotels"}
    assert en["raw_response"]["peopleAlsoAsk"][0]["question"].startswith("Is Ain")
    assert [r["found_by"] for r in saved["normalized"]] == [
        ["en_open", "ar_open"],
        ["en_open"],
        ["ar_open"],
    ]
    assert FAKE_KEY not in json.dumps(saved, ensure_ascii=False)  # the key is never saved

    score.score_all(base_dir)
    with (base_dir / "scores.csv").open(encoding="utf-8") as f:
        [row] = list(csv.DictReader(f))
    assert row["n_results"] == "3"
    assert row["n_with_date"] == "2"  # Serper's `date` is read as published_date
    assert (row["unique_from_en_open"], row["unique_from_ar_open"]) == ("1", "1")
    assert (row["en_open_status"], row["ar_open_status"]) == ("ok", "ok")


@pytest.mark.parametrize(
    "failure, expected",
    [
        ((429, {"message": "Too many requests"}), "RuntimeError: HTTP 429"),
        ((503, {"message": "unavailable"}), "RuntimeError: HTTP 503"),
        (httpx.ReadTimeout("timed out"), "ReadTimeout: timed out"),
    ],
)
def test_serper_errors_are_recorded_not_raised(monkeypatch, base_dir, failure, expected):
    saved, _ = _run(base_dir, monkeypatch, [failure, (200, ORGANIC)])
    en, ar = saved["searches"]
    assert en["status"] == "error" and en["error"].startswith(expected)
    assert FAKE_KEY not in en["error"]
    assert ar["status"] == "ok" and saved["status"] == "ok"


def test_serper_empty_open_search_is_retried_once(monkeypatch, base_dir):
    empty = (200, {"organic": []})
    saved, calls = _run(base_dir, monkeypatch, [empty, empty, (200, ORGANIC)])
    assert len(calls) == 3
    en, ar = saved["searches"]
    assert (en["status"], en["attempts"]) == ("empty", 2)
    assert (ar["status"], ar["attempts"]) == ("ok", 1)


def test_missing_serper_key_is_an_error(monkeypatch, base_dir):
    monkeypatch.setenv("SERPER_API_KEY", "")
    with pytest.raises(RuntimeError, match="SERPER_API_KEY is not set"):
        compare.search_serper("q", {"gl": "eg", "hl": "en", "num": 10})


def test_real_serper_v1_settings():
    v1 = compare.load_settings("serper", "v1")
    assert v1["strategy"] == "mixed" and v1["base"] == {}
    assert v1["searches"] == [
        {"name": "en_open", "queries": "v1", "gl": "eg", "hl": "en", "num": 10},
        {"name": "ar_open", "queries": "v2", "gl": "eg", "hl": "ar", "num": 10},
    ]


def test_site_filter_and_search_query():
    assert compare.site_filter([]) == ""
    assert compare.site_filter(["a.com", "b.eg"]) == " (site:a.com OR site:b.eg)"
    question = {"queries": {"ar_sites": "سؤال"}}
    search = {"name": "ar_sites", "sites": ["youm7.com"]}
    assert compare.search_query(question, search) == "سؤال (site:youm7.com)"


def test_serper_v2_sends_site_operators_and_saves_the_exact_query(monkeypatch, base_dir):
    empty = (200, {"organic": []})
    responses = [(200, ORGANIC), empty, (200, ORGANIC)]  # en_open, ar_sites (empty), en_sites
    calls = _fake_post(monkeypatch, responses)
    [path] = compare.compare("serper", "v2", runs=1, query="obour_q3", base_dir=base_dir, pause=0)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert len(calls) == 3  # the empty site search is not retried
    en_open, ar_sites, en_sites = saved["searches"]
    assert en_open["query"] == "New Obour City shop prices per square meter 2026"
    assert ar_sites["query"] == calls[1]["json"]["q"]
    assert ar_sites["query"].startswith("سعر متر المحلات التجارية في مدينة العبور الجديدة 2026 (")
    assert ar_sites["query"].endswith("OR site:aqarmap.com.eg OR site:sis.gov.eg)")
    assert en_sites["query"].endswith("OR site:knightfrank.com OR site:mped.gov.eg)")
    assert (ar_sites["status"], ar_sites["attempts"]) == ("empty", 1)
    assert calls[1]["json"] == {"q": ar_sites["query"], "gl": "eg", "hl": "ar", "num": 10}
    assert "sites" not in calls[2]["json"]  # the site list is part of q, not a parameter


def test_real_serper_v2_settings():
    v2 = compare.load_settings("serper", "v2")
    assert [s["name"] for s in v2["searches"]] == ["en_open", "ar_sites", "en_sites"]
    assert v2["base"] == {"gl": "eg", "num": 10}
    en_open, ar_sites, en_sites = v2["searches"]
    assert "sites" not in en_open and len(ar_sites["sites"]) == len(en_sites["sites"]) == 10
    v1 = compare.load_settings("serper", "v1")  # unchanged
    assert v1["searches"][0] == {
        "name": "en_open",
        "queries": "v1",
        "gl": "eg",
        "hl": "en",
        "num": 10,
    }


GOTO = "https://www.google.com/goto?url=CAESZwHEIkXXCnNyNIL5"


def test_google_redirect_links_keep_their_real_site():
    raw = {
        "organic": [
            {"title": "T", "link": GOTO + "aaa", "displayedLink": "https://alborsaanews.com › x"},
            {"title": "U", "link": "https://youm7.com/s", "displayedLink": "https://youm7.com › y"},
            {"title": "V", "link": GOTO + "bbb", "displayedLink": "www.Zawya.com › z"},
        ]
    }
    first, second, third = compare.serper_results(raw)
    assert first.url == GOTO + "aaa" and first.source_domain == "alborsaanews.com"
    assert second.source_domain is None  # a normal link needs no source_domain
    assert third.source_domain == "zawya.com"


def test_redirects_are_scored_by_their_real_site_and_not_collapsed(monkeypatch, base_dir):
    ar_body = {
        "organic": [
            {"title": "Same story", "link": GOTO + "1", "displayedLink": "https://youm7.com › a"},
            {"title": "Other story", "link": GOTO + "2", "displayedLink": "https://sis.gov.eg › b"},
        ]
    }
    en_body = {
        "organic": [
            # Same site and title as ar's first redirect, different token: the same result.
            {"title": "Same story", "link": GOTO + "3", "displayedLink": "https://youm7.com › a"},
            {"title": "Third", "link": GOTO + "4", "displayedLink": "https://zawya.com › c"},
        ]
    }
    _fake_post(monkeypatch, [(200, ORGANIC), (200, ar_body), (200, en_body)])
    compare.compare("serper", "v2", runs=1, query="sokhna_q1", base_dir=base_dir, pause=0)
    score.score_all(base_dir)
    with (base_dir / "scores.csv").open(encoding="utf-8") as f:
        [row] = list(csv.DictReader(f))

    # 2 from en_open + 4 redirects, one shared = 5; google.com never counted.
    assert row["n_results"] == "5"
    assert "google.com" not in row["unlisted_domains"]
    assert row["ar_sites_n_citable"] == "2" and row["en_sites_n_citable"] == "2"
    assert row["unique_from_ar_sites"] == "1" and row["unique_from_en_sites"] == "1"
