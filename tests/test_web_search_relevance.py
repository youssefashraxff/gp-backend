"""Tests for experiments/tools/web_search/relevance.py (code-based relevance, dates)."""

from datetime import UTC, datetime

from experiments.tools.web_search.relevance import load_relevance, normalize_text, parse_date

NOW = datetime(2026, 11, 28, tzinfo=UTC)


def test_normalize_text_arabic():
    assert normalize_text("العين السخنة") == "العين السخنه"
    assert normalize_text("إطلاق مشروعات") == "اطلاق مشروعات"
    assert normalize_text("رؤيةُ مصر") == "رؤيه مصر"  # diacritic removed
    assert normalize_text("Ain SOKHNA") == "ain sokhna"


def test_parse_date_formats():
    d = lambda s: (p := parse_date(s, NOW)) and p.date().isoformat()  # noqa: E731
    assert d("Mar 3, 2026") == "2026-03-03"
    assert d("11‏/11‏/2026") == "2026-11-11"  # day/month/year, RTL marks
    assert d("٠٧‏/١٢‏/٢٠٢٥") == "2025-12-07"  # Arabic digits
    assert d("3 days ago") == "2026-11-25"
    assert d("قبل ٣ أيام") == "2026-11-25"
    assert d("2025-02-01T10:00:00Z") == "2025-02-01"
    assert parse_date(None, NOW) is None and parse_date("soon", NOW) is None


def test_relevance_and_freshness():
    rel = load_relevance()
    assert rel is not None
    hit = {"title": "أسعار الشاليهات في العين السخنة", "snippet": "", "url": "https://x.eg/a"}
    place_only = {"title": "Ain Sokhna weather", "snippet": "sunny", "url": "https://x.com"}
    via_url = {"title": "", "snippet": "", "url": "https://nawy.com/new-obour-shop-for-sale"}
    assert rel.is_relevant(hit, "ain_sokhna", "prices")
    assert not rel.is_relevant(place_only, "ain_sokhna", "prices")
    assert rel.is_relevant(via_url, "new_obour", "prices")
    assert not rel.is_relevant(hit, "new_obour", "prices")  # wrong place
    ts = "2026-11-28T12:00:00+00:00"
    assert rel.freshness("Mar 3, 2026", ts) == "fresh"
    assert rel.freshness("15/01/2019", ts) == "old"
    assert rel.freshness(None, ts) == "undated"
