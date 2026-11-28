"""Web search through Serper (Google Search), chosen in X2 over Tavily
(experiments/tools/web_search/reports/2026-11-28_web_search_decision.md).

`sites` restricts the search with Google `site:` operators; the same call with social
domains is the social search (posts are leads, not facts: most are undated).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.shared.settings import settings
from app.shared.tools.base import ToolError, ToolResult, failed, key, ok_json, request, result

TIMEOUT = 15.0  # spec 5.6
URL = "https://google.serper.dev/search"
SOURCE = "Serper (Google Search API)"
SOCIAL_SITES = ["facebook.com", "instagram.com", "x.com", "tiktok.com"]


def build_query(text: str, sites: list[str] | None) -> str:
    if not sites:
        return text
    return f"{text} (" + " OR ".join(f"site:{s}" for s in sites) + ")"


async def web_search(
    text: str,
    lang: str = "en",
    sites: list[str] | None = None,
    months: int | None = None,
    num: int = 10,
) -> ToolResult:
    """Results in Egypt (`gl=eg`), in `lang` ("en" or "ar"); `months` keeps only pages
    dated within that many months."""
    query = {"text": text, "lang": lang, "sites": sites, "months": months, "num": num}
    body: dict = {"q": build_query(text, sites), "gl": "eg", "hl": lang, "num": num}
    if months:
        start = datetime.now(UTC) - timedelta(days=30 * months)
        today = datetime.now(UTC)
        body["tbs"] = (
            f"cdr:1,cd_min:{start.month}/{start.day}/{start.year},"
            f"cd_max:{today.month}/{today.day}/{today.year}"
        )
    try:
        r = await request(
            "serper",
            "POST",
            URL,
            timeout=TIMEOUT,
            json=body,
            headers={"X-API-KEY": key(settings.serper_api_key, "SERPER_API_KEY")},
        )
        organic = ok_json(r, "serper").get("organic", [])
    except ToolError as exc:
        return failed("web_search", SOURCE, query, str(exc))
    data = [
        {
            "url": o.get("link"),
            "title": o.get("title"),
            "snippet": o.get("snippet"),
            "date": o.get("date"),
        }
        for o in organic
    ]
    return result("web_search", SOURCE, query, data)
