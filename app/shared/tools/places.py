"""Google Places API (New): businesses near a site, and one place's details.

Chosen over Foursquare in the A3 experiment (experiments/tools/geo/reports/).
"""

from __future__ import annotations

from typing import Any

from app.shared.settings import settings
from app.shared.tools.base import (
    ToolError,
    ToolResult,
    failed,
    key,
    ok_json,
    request,
    result,
)

TIMEOUT = 10.0  # spec 5.6
NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
NEARBY_SOURCE = "Google Places API (New): searchNearby"
DETAILS_SOURCE = "Google Places API (New): Place Details"
NEARBY_MAX = 20  # the API's maximum per call; there is no next page
NEARBY_FIELDS = ",".join(
    f"places.{f}"
    for f in (
        "id",
        "displayName",
        "primaryType",
        "types",
        "location",
        "rating",
        "userRatingCount",
        "businessStatus",
        "formattedAddress",
        "priceLevel",
        "regularOpeningHours.weekdayDescriptions",
    )
)
DETAILS_FIELDS = (
    "id,displayName,primaryType,rating,userRatingCount,priceLevel,"
    "regularOpeningHours.weekdayDescriptions,reviews"
)


def _place(p: dict[str, Any]) -> dict[str, Any]:
    loc = p.get("location") or {}
    return {
        "place_id": p.get("id"),
        "name": (p.get("displayName") or {}).get("text"),
        "primary_type": p.get("primaryType"),
        "types": p.get("types", []),
        "lat": loc.get("latitude"),
        "lng": loc.get("longitude"),
        "address": p.get("formattedAddress"),
        "rating": p.get("rating"),
        "review_count": p.get("userRatingCount", 0),
        "price_level": p.get("priceLevel"),
        "business_status": p.get("businessStatus"),
        "opening_hours": (p.get("regularOpeningHours") or {}).get("weekdayDescriptions"),
    }


async def places_nearby(lat: float, lng: float, radius_m: float, types: list[str]) -> ToolResult:
    """Places of the given Google types within `radius_m`, nearest first.

    shortcut: at most 20 places per call, flagged as `capped`; split the area into smaller
    circles if an agent needs more than the nearest 20 (in the experiment, 3 km returned the
    same 20 as 1 km in a built-up area).
    """
    query = {"lat": lat, "lng": lng, "radius_m": radius_m, "types": types}
    try:
        r = await request(
            "google_places",
            "POST",
            NEARBY_URL,
            timeout=TIMEOUT,
            headers={
                "X-Goog-Api-Key": key(settings.google_maps_api_key, "GOOGLE_MAPS_API_KEY"),
                "X-Goog-FieldMask": NEARBY_FIELDS,
            },
            json={
                "includedTypes": types,
                "maxResultCount": NEARBY_MAX,
                "rankPreference": "DISTANCE",
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": float(radius_m),
                    }
                },
            },
        )
        places = [_place(p) for p in ok_json(r, "google_places").get("places", [])]
    except ToolError as exc:
        return failed("places_nearby", NEARBY_SOURCE, query, str(exc))
    return result("places_nearby", NEARBY_SOURCE, query, places, capped=len(places) >= NEARBY_MAX)


async def place_details(place_id: str) -> ToolResult:
    """Rating, review count, price level, opening hours and up to 5 reviews (Google picks
    which) with their dates."""
    query = {"place_id": place_id}
    try:
        r = await request(
            "google_places",
            "GET",
            DETAILS_URL.format(place_id=place_id),
            timeout=TIMEOUT,
            headers={
                "X-Goog-Api-Key": key(settings.google_maps_api_key, "GOOGLE_MAPS_API_KEY"),
                "X-Goog-FieldMask": DETAILS_FIELDS,
            },
        )
        p = ok_json(r, "google_places")
    except ToolError as exc:
        return failed("place_details", DETAILS_SOURCE, query, str(exc))
    details = _place(p)
    details["reviews"] = [
        {
            "rating": rv.get("rating"),
            "published_at": rv.get("publishTime"),
            "text": (rv.get("text") or {}).get("text"),
        }
        for rv in p.get("reviews", [])
    ]
    return result("place_details", DETAILS_SOURCE, query, details)
