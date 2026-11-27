"""Merging the results of several searches (strategy runs). Used by compare.py when saving
and by score.py when scoring, so both always agree on what counts as the same URL."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


def normalize_url(url: str) -> str:
    """The key two URLs must share to count as the same result: lowercase host without
    `www.`, path without a trailing `/`; scheme, query string and fragment are dropped.

    `https://WWW.Youm7.com/story/1/?utm=x#top` -> `youm7.com/story/1`
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    if not host:  # not a URL we can parse: compare the text as it is
        return url.strip().rstrip("/").lower()
    return host + parts.path.rstrip("/")


def merge_results(searches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate the `normalized` results of every search by `normalize_url`, keeping which
    searches found each URL (`found_by`). The first URL seen is kept as written. Ordered by
    the best score any search gave the URL (no score last), then by first seen."""
    merged: dict[str, dict[str, Any]] = {}
    for search in searches:
        for result in search.get("normalized") or []:
            key = normalize_url(result.get("url", ""))
            if key not in merged:
                merged[key] = {**result, "found_by": [search["name"]]}
                continue
            entry = merged[key]
            if search["name"] not in entry["found_by"]:
                entry["found_by"].append(search["name"])
            if result.get("score") is not None and (
                entry.get("score") is None or result["score"] > entry["score"]
            ):
                entry["score"] = result["score"]
            if not entry.get("published_date") and result.get("published_date"):
                entry["published_date"] = result["published_date"]
    order = {key: i for i, key in enumerate(merged)}
    return sorted(
        merged.values(),
        key=lambda r: (
            r.get("score") is None,
            -(r.get("score") or 0),
            order[normalize_url(r.get("url", ""))],
        ),
    )
