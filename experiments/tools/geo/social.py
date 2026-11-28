"""Social: what public Facebook, Instagram, X and TikTok posts Google (through Serper)
finds about the site's area. No scraping: only what Google has indexed.

Each question is asked once with all platforms in one `site:` filter, and once per
platform, to see whether one combined call is enough or loses results.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

from experiments.tools.geo.common import TIMEOUT_SECONDS, Call, Keys, require

SERPER_URL = "https://google.serper.dev/search"
MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}


def site_filter(domains: list[str]) -> str:
    return "(" + " OR ".join(f"site:{d}" for d in domains) + ")"


def serper(keys: Keys) -> Any:
    key = require(keys.serper_api_key, "SERPER_API_KEY")

    def fn(p: dict[str, Any]) -> tuple[Any, int]:
        body = {"q": p["q"], "gl": "eg", "hl": p["hl"], "num": p.get("num", 10)}
        r = httpx.post(
            SERPER_URL,
            json=body,
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        raw = r.json()
        return raw, len(raw.get("organic", []))

    return fn


def build_calls(site: dict[str, Any], cases: dict[str, Any], keys: Keys) -> list[Call]:
    calls: list[Call] = []
    platforms: dict[str, str] = cases["platforms"]
    for q in cases["queries"]:
        variants = [("all", list(platforms.values()))]
        variants += [(name, [dom]) for name, dom in platforms.items()]
        for vname, domains in variants:
            params = {"q": f"{q['text']} {site_filter(domains)}", "hl": q["lang"], "num": 10}
            meta = {"query_id": q["id"], "variant": vname, "lang": q["lang"]}
            calls.append(Call("social", "serper", f"{q['id']}_{vname}", params, serper(keys), meta))
    return calls


def followup_calls(results: list[dict[str, Any]], cases: dict[str, Any], keys: Keys) -> list[Call]:
    return []


# ---------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------


def parse_date(text: str | None, now: datetime | None = None) -> datetime | None:
    """Serper dates: "3 days ago", "2 weeks ago", "Nov 5, 2025", "5 Nov 2025"."""
    if not text:
        return None
    now = now or datetime.now(UTC)
    t = text.strip().lower()
    m = re.match(r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}[unit]
        return now - timedelta(days=n * days)
    m = re.match(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", t)
    if m and m.group(1) in MONTHS:
        return datetime(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)), tzinfo=UTC)
    m = re.match(r"(\d{1,2})\s+([a-z]{3})[a-z]*\.?,?\s+(\d{4})", t)
    if m and m.group(2) in MONTHS:
        return datetime(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)), tzinfo=UTC)
    return None


def platform_of(url: str, platforms: dict[str, str]) -> str:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    for name, dom in platforms.items():
        if host == dom or host.endswith("." + dom):
            return name
    return "other"


def score_file(
    payload: dict[str, Any],
    platforms: dict[str, str],
    place_words: list[str],
    now: datetime | None = None,
) -> dict[str, Any]:
    meta = payload.get("meta") or {}
    organic = (payload.get("raw") or {}).get("organic", [])
    now = now or datetime.now(UTC)
    by_platform: dict[str, int] = {}
    dated = recent = relevant = 0
    for o in organic:
        name = platform_of(o.get("link", ""), platforms)
        by_platform[name] = by_platform.get(name, 0) + 1
        when = parse_date(o.get("date"), now)
        if when:
            dated += 1
            if (now - when).days <= 365:
                recent += 1
        text = f"{o.get('title', '')} {o.get('snippet', '')}".lower()
        if any(w.lower() in text for w in place_words):
            relevant += 1
    return {
        "query_id": meta.get("query_id"),
        "variant": meta.get("variant"),
        "lang": meta.get("lang"),
        "n_results": len(organic),
        "n_mentions_place": relevant,
        "n_dated": dated,
        "n_last_12_months": recent,
        "by_platform": "; ".join(f"{k}={v}" for k, v in sorted(by_platform.items())),
        "urls": [o.get("link", "") for o in organic],
    }
