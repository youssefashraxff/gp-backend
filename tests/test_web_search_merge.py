"""Tests for experiments/tools/web_search/merge.py: which URLs count as the same result."""

from experiments.tools.web_search.merge import merge_results, normalize_url


def test_normalize_url():
    key = "youm7.com/story/1"
    assert normalize_url("https://WWW.Youm7.com/story/1/?utm_source=x#top") == key
    assert normalize_url("http://youm7.com/story/1") == key  # scheme ignored
    assert normalize_url("https://youm7.com/story/1?page=2") == key  # query dropped
    assert normalize_url("https://youm7.com/story/2") != key  # a different page
    assert normalize_url("https://english.ahram.org.eg/x") == "english.ahram.org.eg/x"
    assert normalize_url("https://youm7.com/") == "youm7.com"


def test_merge_two_searches_sharing_one_url():
    searches = [
        {
            "name": "ar_restricted",
            "normalized": [
                {"url": "https://www.youm7.com/story/1/", "score": 0.4, "published_date": None},
                {"url": "https://capmas.gov.eg/a", "score": 0.9},
            ],
        },
        {
            "name": "open",
            "normalized": [
                {"url": "https://youm7.com/story/1?utm=x", "score": 0.8, "published_date": "d"},
                {"url": "https://nawy.com/b", "score": None},
            ],
        },
    ]
    merged = merge_results(searches)
    assert [r["url"] for r in merged] == [
        "https://capmas.gov.eg/a",
        "https://www.youm7.com/story/1/",  # first form seen is kept
        "https://nawy.com/b",  # no score: last
    ]
    shared = merged[1]
    assert shared["found_by"] == ["ar_restricted", "open"]
    assert shared["score"] == 0.8 and shared["published_date"] == "d"
