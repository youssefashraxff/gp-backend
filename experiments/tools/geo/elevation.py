"""Elevation: how flat the site is, from Google and from free OpenTopoData datasets.

One grid of points over the plot (to measure slope) plus a ring of points further out (to
see the terrain around it) go to every provider in a single call each. The providers get
exactly the same points, so their answers can be compared point by point.
"""

from __future__ import annotations

from typing import Any

import httpx

from experiments.tools.geo.common import (
    POLITE_HEADERS,
    TIMEOUT_SECONDS,
    Call,
    Keys,
    offset_point,
    require,
)

GOOGLE_ELEVATION_URL = "https://maps.googleapis.com/maps/api/elevation/json"
OPENTOPODATA_URL = "https://api.opentopodata.org/v1/{dataset}"


def grid_points(site: dict[str, Any], cases: dict[str, Any]) -> list[dict[str, Any]]:
    """`grid_n` x `grid_n` points `grid_spacing_m` apart, centred on the pin, then a ring of
    8 points (N, NE, E, ...) at each distance in `ring_m`."""
    lat, lng = site["lat"], site["lng"]
    n = int(cases["grid_n"])
    step = float(cases["grid_spacing_m"])
    half = (n - 1) / 2
    points: list[dict[str, Any]] = []
    for i in range(n):
        for j in range(n):
            plat, plng = offset_point(lat, lng, (i - half) * step, (j - half) * step)
            points.append({"lat": plat, "lng": plng, "part": "grid", "row": i, "col": j})
    dirs = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
    for dist in cases.get("ring_m", []):
        for dn, de in dirs:
            scale = dist / (2**0.5) if dn and de else dist
            plat, plng = offset_point(lat, lng, dn * scale, de * scale)
            points.append({"lat": plat, "lng": plng, "part": f"ring_{dist}"})
    return points


def _locations(points: list[dict[str, Any]]) -> str:
    return "|".join(f"{p['lat']},{p['lng']}" for p in points)


def google_elevation(keys: Keys) -> Any:
    key = require(keys.google_maps_api_key, "GOOGLE_MAPS_API_KEY")

    def fn(p: dict[str, Any]) -> tuple[Any, int]:
        r = httpx.get(
            GOOGLE_ELEVATION_URL,
            params={"locations": _locations(p["points"]), "key": key},
            timeout=TIMEOUT_SECONDS,
        )
        # Not raise_for_status(): its message holds the URL, and this URL holds the key.
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        raw = r.json()
        if raw.get("status") != "OK":
            raise RuntimeError(f"{raw.get('status')}: {raw.get('error_message', '')}")
        return raw, len(raw.get("results", []))

    return fn


def opentopodata(dataset: str) -> Any:
    def fn(p: dict[str, Any]) -> tuple[Any, int]:
        r = httpx.get(
            OPENTOPODATA_URL.format(dataset=dataset),
            params={"locations": _locations(p["points"])},
            headers=POLITE_HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        raw = r.json()
        if raw.get("status") != "OK":
            raise RuntimeError(f"{raw.get('status')}: {raw.get('error', '')}")
        return raw, len(raw.get("results", []))

    return fn


def build_calls(site: dict[str, Any], cases: dict[str, Any], keys: Keys) -> list[Call]:
    points = grid_points(site, cases)
    params = {"points": points}
    meta = {"n_points": len(points), "grid_spacing_m": cases["grid_spacing_m"]}
    calls: list[Call] = []
    for prov in cases["providers"]:
        if prov == "google":
            calls.append(Call("elevation", "google", "grid", params, google_elevation(keys), meta))
        elif prov.startswith("opentopodata_"):
            dataset = prov.removeprefix("opentopodata_")
            calls.append(Call("elevation", prov, "grid", params, opentopodata(dataset), meta))
    return calls


def followup_calls(results: list[dict[str, Any]], cases: dict[str, Any], keys: Keys) -> list[Call]:
    return []


# ---------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------


def heights(payload: dict[str, Any]) -> list[float | None]:
    """Elevation per point, in the order of `params.points` (both providers keep the order)."""
    results = (payload.get("raw") or {}).get("results", [])
    return [r.get("elevation") for r in results]


def score_file(payload: dict[str, Any]) -> dict[str, Any]:
    points = payload["params"]["points"]
    hs = heights(payload)
    spacing = float((payload.get("meta") or {}).get("grid_spacing_m") or 1)
    grid = {
        (pt["row"], pt["col"]): h
        for pt, h in zip(points, hs, strict=False)
        if pt["part"] == "grid" and h is not None
    }
    ring = [h for pt, h in zip(points, hs, strict=False) if pt["part"] != "grid" and h is not None]
    slopes = []
    for (i, j), h in grid.items():
        for di, dj in ((1, 0), (0, 1)):
            other = grid.get((i + di, j + dj))
            if other is not None:
                slopes.append(abs(other - h) / spacing * 100)
    resolutions = [
        r.get("resolution")
        for r in (payload.get("raw") or {}).get("results", [])
        if r.get("resolution") is not None
    ]
    vals = list(grid.values())
    return {
        "n_points": len(hs),
        "n_missing": sum(1 for h in hs if h is None),
        "site_min_m": round(min(vals), 1) if vals else None,
        "site_max_m": round(max(vals), 1) if vals else None,
        "site_relief_m": round(max(vals) - min(vals), 1) if vals else None,
        "site_mean_m": round(sum(vals) / len(vals), 1) if vals else None,
        "max_slope_pct": round(max(slopes), 2) if slopes else None,
        "mean_slope_pct": round(sum(slopes) / len(slopes), 2) if slopes else None,
        "ring_relief_m": round(max(ring) - min(ring), 1) if ring else None,
        "resolution_m": round(sum(resolutions) / len(resolutions), 1) if resolutions else None,
    }


def mean_abs_diff(a: list[float | None], b: list[float | None]) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b, strict=False) if x is not None and y is not None]
    if not pairs:
        return None
    return round(sum(abs(x - y) for x, y in pairs) / len(pairs), 2)
