"""Resolve Google `google.com/goto?url=<token>` links (returned by Serper for `site:`
queries) to the real page URL, and cache them in `redirects.json` so scoring stays offline.

The token can't be decoded, but Google answers the link with a 302 whose Location is the
page. One plain GET per new link, no API credits. Failures are cached as null and retried
on the next call.

Run:  python -m experiments.tools.web_search.resolve
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

BASE_DIR = Path(__file__).resolve().parent
CACHE = "redirects.json"


def is_google_redirect(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    return host == "google.com" and parts.path == "/goto"


def load_redirects(base_dir: Path = BASE_DIR) -> dict[str, str | None]:
    path = base_dir / CACHE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def resolve_one(link: str) -> str | None:
    try:
        r = httpx.get(
            link, follow_redirects=False, timeout=15, headers={"User-Agent": "Mozilla/5.0"}
        )
    except httpx.HTTPError:
        return None
    location = r.headers.get("location") or ""
    return location if r.is_redirect and location.startswith("http") else None


def resolve_all(base_dir: Path = BASE_DIR, pause: float = 0.2) -> tuple[int, int]:
    """Resolve every goto link in the saved Serper runs that isn't cached yet (or failed
    before). Returns (newly resolved, still unresolved)."""
    cache = load_redirects(base_dir)
    links = set()
    for p in (base_dir / "runs" / "serper").rglob("*.json"):
        run = json.loads(p.read_text(encoding="utf-8"))
        for search in run.get("searches") or [{"raw_response": run.get("raw_response")}]:
            for item in (search.get("raw_response") or {}).get("organic") or []:
                if is_google_redirect(item.get("link", "")):
                    links.add(item["link"])
    new = 0
    for link in sorted(links):
        if cache.get(link):
            continue
        cache[link] = resolve_one(link)
        new += cache[link] is not None
        time.sleep(pause)
    (base_dir / CACHE).write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    return new, sum(v is None for v in cache.values())


if __name__ == "__main__":
    resolved, failed = resolve_all()
    print(f"redirects.json: {resolved} newly resolved, {failed} unresolved")
