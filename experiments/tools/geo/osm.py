"""OSM: what OpenStreetMap (through the Overpass API) knows around one site.

Each case is one Overpass query (roads, major roads, land use, buildings, points of
interest, and the areas that contain the pin). Every query is sent to two public Overpass
servers, to see how reliable each one is: the same data, so any difference is an error,
a timeout or a stale copy.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from experiments.tools.geo.common import (
    POLITE_HEADERS,
    TIMEOUT_SECONDS,
    Call,
    Keys,
    age_days,
    haversine_m,
    median,
)

MAJOR = "motorway|trunk|primary|secondary|tertiary"
MAJOR_SET = set(MAJOR.split("|")) | {f"{c}_link" for c in MAJOR.split("|")}
MAJOR_RE = re.compile(rf"^({MAJOR})(_link)?$")
LOCAL = "local"  # endpoint value meaning: answer from the local cache (osm_data.py)


def overpass_query(kind: str, lat: float, lng: float, radius: int) -> str:
    """The Overpass QL text for one kind of question."""
    around = f"(around:{radius},{lat},{lng})"
    head = "[out:json][timeout:60];"
    if kind == "roads":
        return f"{head}way{around}[highway];out meta geom;"
    if kind == "major_roads":
        return f'{head}way{around}[highway~"^({MAJOR})(_link)?$"];out meta geom;'
    if kind == "landuse":
        return f"{head}(way{around}[landuse];relation{around}[landuse];);out meta center;"
    if kind == "buildings":
        return f"{head}way{around}[building];out count;"
    if kind == "pois":
        return (
            f"{head}(node{around}[amenity];node{around}[shop];node{around}[leisure];"
            f"way{around}[amenity];way{around}[shop];way{around}[leisure];);out meta center;"
        )
    if kind == "pin_area":
        return f"{head}is_in({lat},{lng})->.a;area.a;out tags;"
    raise ValueError(f"Unknown OSM case kind {kind!r}")


def overpass(endpoint: str) -> Any:
    def fn(p: dict[str, Any]) -> tuple[Any, int]:
        r = httpx.post(
            endpoint,
            data={"data": p["query"]},
            headers=POLITE_HEADERS,
            timeout=TIMEOUT_SECONDS + 50,
        )
        r.raise_for_status()
        raw = r.json()
        elements = raw.get("elements", [])
        if p["kind"] == "buildings" and elements:
            return raw, int((elements[0].get("tags") or {}).get("total", 0))
        return raw, len(elements)

    return fn


# ---------------------------------------------------------------------------------------
# Local answers (osm v3): the same questions, from the cache osm_data.py builds, returned in
# Overpass's JSON shape so the scoring below works unchanged.
# ---------------------------------------------------------------------------------------


def _xy(lat0: float, lat: float, lng: float) -> tuple[float, float]:
    """Metres east/north of (lat0, 0): flat-earth projection, fine within a few km."""
    k = 111_320.0
    return lng * k * math.cos(math.radians(lat0)), lat * k


def dist_to_line_m(lat: float, lng: float, coords: list[list[float]]) -> float:
    """Shortest distance from a point to a polyline (segments, not just vertices)."""
    px, py = _xy(lat, lat, lng)
    best = math.inf
    pts = [_xy(lat, c[0], c[1]) for c in coords]
    if len(pts) == 1:
        return math.hypot(pts[0][0] - px, pts[0][1] - py)
    for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
        best = min(best, math.hypot(ax + t * dx - px, ay + t * dy - py))
    return best


def point_in_ring(lat: float, lng: float, ring: list[list[float]]) -> bool:
    """Ray casting: is the point inside this closed ring of [lat, lng]?"""
    inside = False
    for (a_lat, a_lng), (b_lat, b_lng) in zip(ring, ring[1:] + ring[:1], strict=False):
        if (a_lat > lat) != (b_lat > lat):
            cross = a_lng + (lat - a_lat) / (b_lat - a_lat) * (b_lng - a_lng)
            if lng < cross:
                inside = not inside
    return inside


def in_area(lat: float, lng: float, area: dict[str, Any]) -> bool:
    for r in area["rings"]:
        if point_in_ring(lat, lng, r["outer"]) and not any(
            point_in_ring(lat, lng, h) for h in r["inner"]
        ):
            return True
    return False


def _near_box(lat: float, lng: float, radius: float) -> list[float]:
    dlat = radius / 111_320.0
    dlng = radius / (111_320.0 * math.cos(math.radians(lat)))
    return [lat - dlat, lng - dlng, lat + dlat, lng + dlng]


def _bbox_hit(a: list[float], b: list[float]) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _road_bbox(road: dict[str, Any]) -> list[float]:
    if "bbox" not in road:
        lats = [c[0] for c in road["coords"]]
        lngs = [c[1] for c in road["coords"]]
        road["bbox"] = [min(lats), min(lngs), max(lats), max(lngs)]
    return road["bbox"]


def local_query(cache: dict[str, Any], kind: str, lat: float, lng: float, radius: int) -> list:
    """The elements Overpass would return for this question, from the local cache."""
    near = _near_box(lat, lng, radius)
    if kind in ("roads", "major_roads"):
        out = []
        for road in cache["roads"]:
            if kind == "major_roads" and not MAJOR_RE.match(road["tags"].get("highway", "")):
                continue
            if (
                _bbox_hit(_road_bbox(road), near)
                and dist_to_line_m(lat, lng, road["coords"]) <= radius
            ):
                out.append(
                    {
                        "type": "way",
                        "id": road["id"],
                        "tags": road["tags"],
                        "timestamp": road["ts"],
                        "geometry": [{"lat": c[0], "lon": c[1]} for c in road["coords"]],
                    }
                )
        return out
    if kind == "landuse":
        out = []
        for area in cache["areas"]:
            if "landuse" not in area["tags"] or not _bbox_hit(area["bbox"], near):
                continue
            close = in_area(lat, lng, area) or any(
                dist_to_line_m(lat, lng, r["outer"]) <= radius for r in area["rings"]
            )
            if close:
                b = area["bbox"]
                out.append(
                    {
                        "type": "area",
                        "id": area["id"],
                        "tags": area["tags"],
                        "timestamp": area["ts"],
                        "center": {"lat": (b[0] + b[2]) / 2, "lon": (b[1] + b[3]) / 2},
                    }
                )
        return out
    if kind == "pin_area":
        return [
            {"type": "area", "id": a["id"], "tags": a["tags"]}
            for a in cache["areas"]
            if in_area(lat, lng, a)
        ]
    if kind == "buildings":
        total = sum(
            1
            for b in cache["buildings"]
            if near[0] <= b[0] <= near[2]
            and near[1] <= b[1] <= near[3]
            and haversine_m(lat, lng, b[0], b[1]) <= radius
        )
        return [{"type": "count", "tags": {"total": str(total)}}]
    if kind == "pois":
        return [
            {
                "type": "node",
                "id": poi["id"],
                "tags": poi["tags"],
                "lat": poi["lat"],
                "lon": poi["lng"],
                "timestamp": poi["ts"],
            }
            for poi in cache["pois"]
            if near[0] <= poi["lat"] <= near[2]
            and near[1] <= poi["lng"] <= near[3]
            and haversine_m(lat, lng, poi["lat"], poi["lng"]) <= radius
        ]
    raise ValueError(f"Unknown OSM case kind {kind!r}")


def local(cache_file: Path) -> Any:
    def fn(p: dict[str, Any]) -> tuple[Any, int]:
        from experiments.tools.geo.osm_data import load_cache

        cache = load_cache(cache_file)
        elements = local_query(cache, p["kind"], p["lat"], p["lng"], p["radius"])
        raw = {
            "osm3s": {
                "timestamp_osm_base": cache["meta"]["osm_data_timestamp"],
                "source": cache["meta"]["source_file"],
            },
            "elements": elements,
        }
        if p["kind"] == "buildings":
            return raw, int(elements[0]["tags"]["total"])
        return raw, len(elements)

    return fn


def build_calls(site: dict[str, Any], cases: dict[str, Any], keys: Keys) -> list[Call]:
    from experiments.tools.geo.osm_data import cache_path

    calls: list[Call] = []
    lat, lng = site["lat"], site["lng"]
    for name, endpoint in cases["endpoints"].items():
        for c in cases["cases"]:
            radius = int(c.get("radius_m", 0))
            case = f"{c['kind']}_r{radius}" if radius else c["kind"]
            params = {
                "kind": c["kind"],
                "radius": radius,
                "lat": lat,
                "lng": lng,
                "query": overpass_query(c["kind"], lat, lng, radius),
            }
            meta = {"kind": c["kind"], "radius": radius}
            fn = local(cache_path(cases["version"])) if endpoint == LOCAL else overpass(endpoint)
            calls.append(Call("osm", name, case, params, fn, meta))
    return calls


def followup_calls(results: list[dict[str, Any]], cases: dict[str, Any], keys: Keys) -> list[Call]:
    return []


# ---------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------


def score_file(payload: dict[str, Any]) -> dict[str, Any]:
    p = payload["params"]
    kind = p["kind"]
    elements = (payload.get("raw") or {}).get("elements", [])
    ages = [a for a in (age_days(e.get("timestamp")) for e in elements) if a is not None]
    row: dict[str, Any] = {
        "kind": kind,
        "radius_m": p.get("radius"),
        "n_elements": len(elements),
        "median_edit_age_days": median(ages),
        "newest_edit_days": min(ages) if ages else None,
    }
    if kind in ("roads", "major_roads"):
        classes = Counter((e.get("tags") or {}).get("highway", "") for e in elements)
        named = [e for e in elements if (e.get("tags") or {}).get("name")]
        best: tuple[float, str, str] | None = None
        for e in elements:
            tags = e.get("tags") or {}
            if tags.get("highway") not in MAJOR_SET:
                continue
            geom = e.get("geometry") or []
            d = (
                dist_to_line_m(p["lat"], p["lng"], [[g["lat"], g["lon"]] for g in geom])
                if geom
                else None
            )
            if d is not None and (best is None or d < best[0]):
                label = tags.get("name:en") or tags.get("name") or tags.get("ref") or "(unnamed)"
                best = (d, tags["highway"], label)
        major_names = sorted(
            {
                (e.get("tags") or {}).get("name:en") or (e.get("tags") or {}).get("name", "")
                for e in elements
                if (e.get("tags") or {}).get("highway") in MAJOR_SET
            }
            - {""}
        )
        row.update(
            {
                "n_named": len(named),
                "road_classes": "; ".join(f"{k}={v}" for k, v in classes.most_common()),
                "nearest_major_m": round(best[0]) if best else None,
                "nearest_major_class": best[1] if best else None,
                "nearest_major_name": best[2] if best else None,
                "major_road_names": " | ".join(major_names[:15]),
            }
        )
    elif kind == "landuse":
        uses = Counter((e.get("tags") or {}).get("landuse", "") for e in elements)
        row["landuse"] = "; ".join(f"{k}={v}" for k, v in uses.most_common())
    elif kind == "buildings":
        tags = (elements[0].get("tags") or {}) if elements else {}
        row["n_buildings"] = int(tags.get("total", 0) or 0)
    elif kind == "pois":
        kinds = Counter(
            (e.get("tags") or {}).get("amenity")
            or (e.get("tags") or {}).get("shop")
            or (e.get("tags") or {}).get("leisure")
            or ""
            for e in elements
        )
        row.update(
            {
                "n_named": sum(1 for e in elements if (e.get("tags") or {}).get("name")),
                "poi_kinds": "; ".join(f"{k}={v}" for k, v in kinds.most_common(15)),
            }
        )
    elif kind == "pin_area":
        labels = []
        for e in elements:
            t = e.get("tags") or {}
            what = t.get("landuse") or t.get("boundary") or t.get("place") or t.get("type")
            labels.append(f"{t.get('name:en') or t.get('name') or '(unnamed)'} [{what}]")
        row["pin_inside"] = " | ".join(labels)
    return row
