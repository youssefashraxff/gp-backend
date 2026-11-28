"""OpenStreetMap around a site, from a local copy of the data.

The A3 experiment found the public Overpass servers unusable (7 of 80 calls answered), so the
data is read once from Geofabrik's Egypt extract into a small cache and queried locally.

Build or refresh the cache (needs the `osmium` package, in the dev extras):
    # download https://download.geofabrik.de/africa/egypt-latest.osm.pbf first
    python -m app.shared.tools.osm --source egypt-latest.osm.pbf

Use it for roads and access. Buildings are not kept: OSM has none in new cities like Obour,
and land use there is thin, so "nothing mapped" must be escalated, never read as empty land.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.shared.tools.base import ToolResult, failed, result

# Areas the cache covers: (min_lat, min_lng, max_lat, max_lng). Add a box and rebuild to cover
# a new area; a site outside every box gets an error result, which the agent escalates.
BOXES: dict[str, tuple[float, float, float, float]] = {
    "greater_cairo": (29.75, 30.75, 30.50, 31.95),  # Cairo, Giza, 6th of October, New Capital,
    # Obour, New Obour, 10th of Ramadan
    "sokhna_coast": (29.00, 32.15, 29.75, 32.75),  # Ain Sokhna to Zafarana
    "new_mansoura": (31.35, 31.25, 31.60, 31.65),
    "new_sohag": (26.40, 31.45, 26.75, 31.95),
}
MAJOR = re.compile(r"^(motorway|trunk|primary|secondary|tertiary)(_link)?$")
ROAD_TAGS = ("highway", "name", "name:en", "ref")
AREA_KEYS = ("landuse", "boundary", "place")
AREA_TAGS = (*AREA_KEYS, "admin_level", "name", "name:en")
POI_KEYS = ("amenity", "shop", "leisure")
POI_TAGS = (*POI_KEYS, "name", "name:en", "brand")


# ---------------------------------------------------------------------------------------
# Building the cache (offline, once per refresh)
# ---------------------------------------------------------------------------------------


def _bbox(coords: list[list[float]]) -> list[float]:
    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    return [min(lats), min(lngs), max(lats), max(lngs)]


def _hits(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _in_boxes(bbox: list[float], boxes: dict[str, tuple[float, ...]]) -> bool:
    return any(_hits(bbox, box) for box in boxes.values())


def build_cache(source: Path, boxes: dict[str, tuple[float, ...]] = BOXES) -> dict[str, Any]:
    """Read the .osm.pbf once and keep roads, areas and points of interest inside `boxes`."""
    import osmium  # dev-only dependency: only the cache build needs it
    import osmium.io
    import osmium.osm

    out: dict[str, list[Any]] = {"roads": [], "areas": [], "pois": []}

    def tags(obj: Any, keys: tuple[str, ...]) -> dict[str, str]:
        return {k: obj.tags[k] for k in keys if k in obj.tags}

    def ts(obj: Any) -> str | None:
        try:
            return obj.timestamp.isoformat()
        except Exception:  # noqa: BLE001 (a file without timestamps)
            return None

    class Handler(osmium.SimpleHandler):
        def node(self, n: Any) -> None:
            if any(k in n.tags for k in POI_KEYS) and n.location.valid():
                pt = [round(n.location.lat, 6), round(n.location.lon, 6)]
                if _in_boxes(pt + pt, boxes):
                    out["pois"].append(
                        {
                            "id": f"n{n.id}",
                            "tags": tags(n, POI_TAGS),
                            "lat": pt[0],
                            "lng": pt[1],
                            "ts": ts(n),
                        }
                    )

        def way(self, w: Any) -> None:
            is_road = "highway" in w.tags
            is_poi = any(k in w.tags for k in POI_KEYS)
            if not (is_road or is_poi):
                return
            coords = [[round(nd.lat, 6), round(nd.lon, 6)] for nd in w.nodes if nd.location.valid()]
            if not coords or not _in_boxes(_bbox(coords), boxes):
                return
            if is_road:
                out["roads"].append(
                    {
                        "id": f"w{w.id}",
                        "tags": tags(w, ROAD_TAGS),
                        "bbox": _bbox(coords),
                        "coords": coords,
                        "ts": ts(w),
                    }
                )
            if is_poi:
                out["pois"].append(
                    {
                        "id": f"w{w.id}",
                        "tags": tags(w, POI_TAGS),
                        "lat": round(sum(c[0] for c in coords) / len(coords), 6),
                        "lng": round(sum(c[1] for c in coords) / len(coords), 6),
                        "ts": ts(w),
                    }
                )

        def area(self, a: Any) -> None:
            if not any(k in a.tags for k in AREA_KEYS):
                return
            rings = [
                {
                    "outer": [[round(nd.lat, 6), round(nd.lon, 6)] for nd in outer],
                    "inner": [
                        [[round(nd.lat, 6), round(nd.lon, 6)] for nd in inner]
                        for inner in a.inner_rings(outer)
                    ],
                }
                for outer in a.outer_rings()
            ]
            if not rings:
                return
            bbox = _bbox([c for r in rings for c in r["outer"]])
            if _in_boxes(bbox, boxes):
                kind = "w" if a.from_way() else "r"
                out["areas"].append(
                    {
                        "id": f"{kind}{a.orig_id()}",
                        "tags": tags(a, AREA_TAGS),
                        "bbox": bbox,
                        "rings": rings,
                        "ts": ts(a),
                    }
                )

    Handler().apply_file(str(source), locations=True)
    reader = osmium.io.Reader(str(source), osmium.osm.osm_entity_bits.NOTHING)
    data_date = reader.header().get("osmosis_replication_timestamp") or ""
    reader.close()
    return {
        "meta": {
            "source_file": source.name,
            "data_date": data_date,
            "built_at": datetime.now(UTC).isoformat(),
            "boxes": boxes,
            "counts": {k: len(v) for k, v in out.items()},
        },
        **out,
    }


# ---------------------------------------------------------------------------------------
# Querying it
# ---------------------------------------------------------------------------------------

_loaded: dict[str, dict[str, Any]] = {}


def load(path: Path) -> dict[str, Any] | None:
    if str(path) not in _loaded:
        if not path.exists():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as f:
            _loaded[str(path)] = json.load(f)
    return _loaded[str(path)]


def _xy(lat0: float, lat: float, lng: float) -> tuple[float, float]:
    """Metres on a flat local projection: accurate enough within a few km."""
    return lng * 111_320.0 * math.cos(math.radians(lat0)), lat * 111_320.0


def distance_m(lat: float, lng: float, coords: list[list[float]]) -> float:
    """Shortest distance from the point to a line or point (segments, not just vertices)."""
    px, py = _xy(lat, lat, lng)
    pts = [_xy(lat, c[0], c[1]) for c in coords]
    if len(pts) == 1:
        return math.hypot(pts[0][0] - px, pts[0][1] - py)
    best = math.inf
    for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
        best = min(best, math.hypot(ax + t * dx - px, ay + t * dy - py))
    return best


def _in_ring(lat: float, lng: float, ring: list[list[float]]) -> bool:
    inside = False
    for (a_lat, a_lng), (b_lat, b_lng) in zip(ring, ring[1:] + ring[:1], strict=False):
        if (a_lat > lat) != (b_lat > lat):
            if lng < a_lng + (lat - a_lat) / (b_lat - a_lat) * (b_lng - a_lng):
                inside = not inside
    return inside


def _in_area(lat: float, lng: float, area: dict[str, Any]) -> bool:
    return any(
        _in_ring(lat, lng, r["outer"]) and not any(_in_ring(lat, lng, h) for h in r["inner"])
        for r in area["rings"]
    )


def _near(lat: float, lng: float, radius: float) -> list[float]:
    dlat = radius / 111_320.0
    dlng = radius / (111_320.0 * math.cos(math.radians(lat)))
    return [lat - dlat, lng - dlng, lat + dlat, lng + dlng]


def _name(t: dict[str, str]) -> str | None:
    return t.get("name:en") or t.get("name") or t.get("ref")


def query(
    cache: dict[str, Any], lat: float, lng: float, radius_m: float, major_radius_m: float
) -> dict[str, Any]:
    near, far = _near(lat, lng, radius_m), _near(lat, lng, major_radius_m)
    roads, major = [], None
    for road in cache["roads"]:
        is_major = bool(MAJOR.match(road["tags"].get("highway", "")))
        if not _hits(road["bbox"], far if is_major else near):
            continue
        d = distance_m(lat, lng, road["coords"])
        item = {
            "name": _name(road["tags"]),
            "highway": road["tags"].get("highway"),
            "distance_m": round(d),
        }
        if d <= radius_m:
            roads.append(item)
        if is_major and d <= major_radius_m and (major is None or d < major["distance_m"]):
            major = item
    landuse = Counter(
        a["tags"]["landuse"]
        for a in cache["areas"]
        if "landuse" in a["tags"]
        and _hits(a["bbox"], near)
        and (
            _in_area(lat, lng, a)
            or any(distance_m(lat, lng, r["outer"]) <= radius_m for r in a["rings"])
        )
    )
    inside = [
        {"name": _name(a["tags"]), "kind": next(a["tags"][k] for k in AREA_KEYS if k in a["tags"])}
        for a in cache["areas"]
        if _hits(a["bbox"], [lat, lng, lat, lng]) and _in_area(lat, lng, a)
    ]
    pois = []
    for p in cache["pois"]:
        if near[0] <= p["lat"] <= near[2] and near[1] <= p["lng"] <= near[3]:
            d = distance_m(lat, lng, [[p["lat"], p["lng"]]])
            if d <= radius_m:
                kind = next((p["tags"][k] for k in POI_KEYS if k in p["tags"]), None)
                pois.append(
                    {
                        "name": _name(p["tags"]),
                        "kind": kind,
                        "lat": p["lat"],
                        "lng": p["lng"],
                        "distance_m": round(d),
                    }
                )
    return {
        "inside": inside,
        "nearest_major_road": major,
        "roads": sorted(roads, key=lambda r: r["distance_m"]),
        "landuse": dict(landuse),
        "pois": sorted(pois, key=lambda p: p["distance_m"]),
    }


async def osm_around(
    lat: float, lng: float, radius_m: float = 1000, major_radius_m: float = 3000
) -> ToolResult:
    """Roads (with the nearest major road within `major_radius_m`), land use, points of
    interest and the areas containing the point, from the local OSM cache."""
    from app.shared.settings import settings

    args = {"lat": lat, "lng": lng, "radius_m": radius_m, "major_radius_m": major_radius_m}
    cache = await asyncio.to_thread(load, settings.osm_cache_path)
    if cache is None:
        return failed(
            "osm_around",
            "OpenStreetMap (local copy)",
            args,
            f"no OSM cache at {settings.osm_cache_path}; build it with "
            "python -m app.shared.tools.osm",
        )
    source = f"OpenStreetMap, Geofabrik Egypt extract of {cache['meta']['data_date']} (local copy)"
    if not _in_boxes([lat, lng, lat, lng], cache["meta"]["boxes"]):
        return failed("osm_around", source, args, "outside the OSM cache's coverage")
    data = await asyncio.to_thread(query, cache, lat, lng, radius_m, major_radius_m)
    has_any = data["roads"] or data["nearest_major_road"] or data["landuse"] or data["pois"]
    return result("osm_around", source, args, data if has_any else None)


def main() -> None:
    from app.shared.settings import settings

    parser = argparse.ArgumentParser(description="Build the local OSM cache")
    parser.add_argument("--source", required=True, help="path to egypt-latest.osm.pbf")
    parser.add_argument("--delete-source", action="store_true")
    args = parser.parse_args()
    source = Path(args.source).expanduser()
    print(f"Reading {source} ({source.stat().st_size / 1e6:.0f} MB), a few minutes...")
    cache = build_cache(source)
    path = settings.osm_cache_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    print(
        f"Wrote {path} ({path.stat().st_size / 1e6:.1f} MB): {cache['meta']['counts']}, "
        f"data date {cache['meta']['data_date'] or 'unknown'}"
    )
    if args.delete_source:
        source.unlink()
        print(f"Deleted {source}")


if __name__ == "__main__":
    main()
