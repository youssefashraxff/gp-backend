"""OSM: what OpenStreetMap (through the Overpass API) knows around one site.

Each case is one Overpass query (roads, major roads, land use, buildings, points of
interest, and the areas that contain the pin). Every query is sent to two public Overpass
servers, to see how reliable each one is: the same data, so any difference is an error,
a timeout or a stale copy.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import httpx

from experiments.tools.geo.common import TIMEOUT_SECONDS, Call, Keys, age_days, haversine_m, median

MAJOR = "motorway|trunk|primary|secondary|tertiary"
MAJOR_SET = set(MAJOR.split("|")) | {f"{c}_link" for c in MAJOR.split("|")}


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
        r = httpx.post(endpoint, data={"data": p["query"]}, timeout=TIMEOUT_SECONDS + 30)
        r.raise_for_status()
        raw = r.json()
        elements = raw.get("elements", [])
        if p["kind"] == "buildings" and elements:
            return raw, int((elements[0].get("tags") or {}).get("total", 0))
        return raw, len(elements)

    return fn


def build_calls(site: dict[str, Any], cases: dict[str, Any], keys: Keys) -> list[Call]:
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
            calls.append(Call("osm", name, case, params, overpass(endpoint), meta))
    return calls


def followup_calls(results: list[dict[str, Any]], cases: dict[str, Any], keys: Keys) -> list[Call]:
    return []


# ---------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------


def nearest_point_m(lat: float, lng: float, geometry: list[dict[str, float]]) -> float | None:
    """Distance from the pin to the closest vertex of a way (vertices are dense enough on
    OSM roads for this to be within a few tens of metres)."""
    if not geometry:
        return None
    return min(haversine_m(lat, lng, g["lat"], g["lon"]) for g in geometry)


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
            d = nearest_point_m(p["lat"], p["lng"], e.get("geometry") or [])
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
