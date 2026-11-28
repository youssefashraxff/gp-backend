"""Places: Google Places API (New) vs Foursquare Places, around one site.

For every category and radius in the case file, each provider is asked for the businesses
around the pin. Then, for a few Google places with reviews, Place Details is called to see
how fresh the reviews are (the Competitors agent needs dated reviews).
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from experiments.tools.geo.common import (
    TIMEOUT_SECONDS,
    Call,
    Keys,
    age_days,
    haversine_m,
    median,
    require,
)

GOOGLE_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
GOOGLE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
FSQ_SEARCH_URL = "https://places-api.foursquare.com/places/search"
FSQ_API_VERSION = "2025-06-17"

GOOGLE_NEARBY_FIELDS = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.primaryType",
        "places.types",
        "places.location",
        "places.rating",
        "places.userRatingCount",
        "places.businessStatus",
        "places.regularOpeningHours.weekdayDescriptions",
        "places.formattedAddress",
    ]
)
GOOGLE_DETAILS_FIELDS = "id,displayName,rating,userRatingCount,reviews.publishTime,reviews.rating"


# ---------------------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------------------


def google_nearby(keys: Keys) -> Any:
    key = require(keys.google_maps_api_key, "GOOGLE_MAPS_API_KEY")

    def fn(p: dict[str, Any]) -> tuple[Any, int]:
        body = {
            "includedTypes": p["types"],
            "maxResultCount": 20,  # the API maximum; there is no next page
            "rankPreference": "DISTANCE",
            "languageCode": "en",
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": p["lat"], "longitude": p["lng"]},
                    "radius": float(p["radius"]),
                }
            },
        }
        r = httpx.post(
            GOOGLE_NEARBY_URL,
            json=body,
            headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": GOOGLE_NEARBY_FIELDS},
            timeout=TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        raw = r.json()
        return raw, len(raw.get("places", []))

    return fn


def google_details(keys: Keys) -> Any:
    key = require(keys.google_maps_api_key, "GOOGLE_MAPS_API_KEY")

    def fn(p: dict[str, Any]) -> tuple[Any, int]:
        r = httpx.get(
            GOOGLE_DETAILS_URL.format(place_id=p["place_id"]),
            headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": GOOGLE_DETAILS_FIELDS},
            timeout=TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        raw = r.json()
        return raw, len(raw.get("reviews", []))

    return fn


def fsq_search(keys: Keys) -> Any:
    key = require(keys.foursquare_api_key, "FOURSQUARE_API_KEY")

    def fn(p: dict[str, Any]) -> tuple[Any, int]:
        r = httpx.get(
            FSQ_SEARCH_URL,
            params={
                "ll": f"{p['lat']},{p['lng']}",
                "radius": int(p["radius"]),
                "query": p["query"],
                "limit": 50,
                "sort": "DISTANCE",
            },
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
                "X-Places-Api-Version": FSQ_API_VERSION,
            },
            timeout=TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        raw = r.json()
        return raw, len(raw.get("results", []))

    return fn


def build_calls(site: dict[str, Any], cases: dict[str, Any], keys: Keys) -> list[Call]:
    """The search calls. Details calls come after, from `followup_calls`."""
    calls: list[Call] = []
    lat, lng = site["lat"], site["lng"]
    providers = cases.get("providers", ["google", "foursquare"])
    for radius in cases["radii_m"]:
        for cat in cases["categories"]:
            case = f"{cat['id']}_r{radius}"
            meta = {"category": cat["id"], "radius": radius}
            if "google" in providers:
                params = {"lat": lat, "lng": lng, "radius": radius, "types": cat["google_types"]}
                calls.append(Call("places", "google", case, params, google_nearby(keys), meta))
            if "foursquare" in providers:
                params = {"lat": lat, "lng": lng, "radius": radius, "query": cat["fsq_query"]}
                calls.append(Call("places", "foursquare", case, params, fsq_search(keys), meta))
    return calls


def followup_calls(results: list[dict[str, Any]], cases: dict[str, Any], keys: Keys) -> list[Call]:
    """Place Details for the nearest Google places that have reviews (one per place)."""
    n = int(cases.get("details_max", 0))
    seen: dict[str, tuple[float, str]] = {}
    for res in results:
        if res["provider"] != "google" or res["status"] != "ok":
            continue
        for item in items(res):
            if item["n_reviews"] and item["id"] not in seen:
                seen[item["id"]] = (item["distance_m"], item["name"])
    nearest = sorted(seen.items(), key=lambda kv: kv[1][0])[:n]
    return [
        Call(
            "places",
            "google",
            f"details_{i + 1}",
            {"place_id": pid},
            google_details(keys),
            {"category": "details", "name": name, "distance_m": dist},
        )
        for i, (pid, (dist, name)) in enumerate(nearest)
    ]


# ---------------------------------------------------------------------------------------
# Scoring (reads saved files only)
# ---------------------------------------------------------------------------------------


def items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The places in one run file, in one shape for both providers."""
    raw = payload.get("raw") or {}
    p = payload["params"]
    out: list[dict[str, Any]] = []
    if payload["provider"] == "google" and "places" in raw:
        for pl in raw.get("places", []):
            loc = pl.get("location") or {}
            plat, plng = loc.get("latitude"), loc.get("longitude")
            out.append(
                {
                    "id": pl.get("id", ""),
                    "name": (pl.get("displayName") or {}).get("text", ""),
                    "lat": plat,
                    "lng": plng,
                    "distance_m": _dist(p, plat, plng),
                    "rating": pl.get("rating"),
                    "n_reviews": pl.get("userRatingCount") or 0,
                    "has_hours": bool(
                        (pl.get("regularOpeningHours") or {}).get("weekdayDescriptions")
                    ),
                    "operational": pl.get("businessStatus") == "OPERATIONAL",
                    "category": pl.get("primaryType"),
                    "refreshed": None,
                    "closed": pl.get("businessStatus") == "CLOSED_PERMANENTLY",
                }
            )
    elif payload["provider"] == "foursquare":
        for pl in raw.get("results", []):
            plat, plng = pl.get("latitude"), pl.get("longitude")
            cats = pl.get("categories") or []
            out.append(
                {
                    "id": pl.get("fsq_place_id", ""),
                    "name": pl.get("name", ""),
                    "lat": plat,
                    "lng": plng,
                    "distance_m": _dist(p, plat, plng),
                    "rating": pl.get("rating"),
                    "n_reviews": (pl.get("stats") or {}).get("total_ratings") or 0,
                    "has_hours": bool(pl.get("hours")),
                    "operational": not pl.get("date_closed"),
                    "category": cats[0].get("name") if cats else None,
                    "refreshed": pl.get("date_refreshed"),
                    "closed": bool(pl.get("date_closed")),
                }
            )
    return out


def _dist(p: dict[str, Any], lat: Any, lng: Any) -> float:
    if lat is None or lng is None or "lat" not in p:
        return float("nan")
    return round(haversine_m(p["lat"], p["lng"], lat, lng), 1)


def score_file(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("meta") or {}
    row: dict[str, Any] = {
        "category": meta.get("category"),
        "radius_m": meta.get("radius"),
    }
    if meta.get("category") == "details":
        reviews = (payload.get("raw") or {}).get("reviews", [])
        ages = [a for a in (age_days(rv.get("publishTime")) for rv in reviews) if a is not None]
        row.update(
            {
                "place_name": meta.get("name"),
                "n_reviews_returned": len(reviews),
                "newest_review_days": min(ages) if ages else None,
                "oldest_review_days": max(ages) if ages else None,
            }
        )
        return row
    its = items(payload)
    radius = meta.get("radius") or 0
    dists = [i["distance_m"] for i in its if i["distance_m"] == i["distance_m"]]
    refreshed = [a for a in (age_days(i["refreshed"]) for i in its) if a is not None]
    row.update(
        {
            "n_places": len(its),
            "n_within_radius": sum(1 for d in dists if d <= radius * 1.05),
            "n_with_rating": sum(1 for i in its if i["rating"] is not None),
            "n_with_reviews": sum(1 for i in its if i["n_reviews"]),
            "median_reviews": median([float(i["n_reviews"]) for i in its if i["n_reviews"]]),
            "n_with_hours": sum(1 for i in its if i["has_hours"]),
            "n_closed": sum(1 for i in its if i["closed"]),
            "nearest_m": round(min(dists)) if dists else None,
            "median_refreshed_days": median(refreshed),
            "names": " | ".join(i["name"] for i in its[:10]),
        }
    )
    return row


def _norm_name(name: str) -> set[str]:
    tokens = re.findall(r"\w+", name.lower())
    return {t for t in tokens if len(t) > 1}


def same_place(a: dict[str, Any], b: dict[str, Any], max_m: float = 150.0) -> bool:
    """Two places from different providers are the same if they are close and share a name."""
    if None in (a["lat"], a["lng"], b["lat"], b["lng"]):
        return False
    if haversine_m(a["lat"], a["lng"], b["lat"], b["lng"]) > max_m:
        return False
    ta, tb = _norm_name(a["name"]), _norm_name(b["name"])
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / min(len(ta), len(tb))
    return overlap >= 0.5


def overlap(google: list[dict[str, Any]], fsq: list[dict[str, Any]]) -> dict[str, int]:
    """How many places both providers found, and how many only one of them found."""
    matched_f: set[int] = set()
    both = 0
    for g in google:
        for j, f in enumerate(fsq):
            if j not in matched_f and same_place(g, f):
                matched_f.add(j)
                both += 1
                break
    return {
        "both": both,
        "only_google": len(google) - both,
        "only_foursquare": len(fsq) - len(matched_f),
    }
