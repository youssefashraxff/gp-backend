"""Google Elevation: height above sea level for a list of points (spec Q6, confirmed by the
A3 experiment). The slope over a plot is computed by the Site analysis agent from a grid."""

from __future__ import annotations

from app.shared.settings import settings
from app.shared.tools.base import ToolError, ToolResult, failed, key, ok_json, request, result

TIMEOUT = 10.0
URL = "https://maps.googleapis.com/maps/api/elevation/json"
SOURCE = "Google Maps Elevation API"
MAX_POINTS = 512  # the API's limit per request


async def elevation(points: list[tuple[float, float]]) -> ToolResult:
    query = {"points": [list(p) for p in points]}
    try:
        if not 0 < len(points) <= MAX_POINTS:
            raise ToolError(f"need 1 to {MAX_POINTS} points, got {len(points)}")
        r = await request(
            "google_elevation",
            "GET",
            URL,
            timeout=TIMEOUT,
            params={
                "locations": "|".join(f"{lat},{lng}" for lat, lng in points),
                "key": key(settings.google_maps_api_key, "GOOGLE_MAPS_API_KEY"),
            },
        )
        raw = ok_json(r, "google_elevation")
        if raw.get("status") != "OK":
            raise ToolError(f"google_elevation: {raw.get('status')}")
    except ToolError as exc:
        return failed("elevation", SOURCE, query, str(exc))
    data = [
        {
            "lat": x["location"]["lat"],
            "lng": x["location"]["lng"],
            "elevation_m": round(x["elevation"], 1),
            "resolution_m": round(x["resolution"], 1),
        }
        for x in raw.get("results", [])
    ]
    return result("elevation", SOURCE, query, data)
