"""Google Routes: drive time between two points at a given departure time, with traffic.

Chosen in the A3 experiment: the free alternatives have no traffic, and traffic moved drive
times by 8-27 % by time of day. Ask at a few fixed times and report the range.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.shared.settings import settings
from app.shared.tools.base import ToolError, ToolResult, failed, key, ok_json, request, result

TIMEOUT = 10.0
URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
SOURCE = "Google Routes API: computeRoutes (traffic-aware)"
FIELDS = "routes.duration,routes.distanceMeters"


def _point(lat: float, lng: float) -> dict:
    return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}


async def travel_time(
    origin: tuple[float, float], destination: tuple[float, float], depart_at: datetime
) -> ToolResult:
    """Predicted driving minutes and km. `depart_at` must be in the future (Google rejects
    past times for traffic)."""
    query = {
        "origin": list(origin),
        "destination": list(destination),
        "depart_at": depart_at.isoformat(),
    }
    try:
        if depart_at.tzinfo is None or depart_at <= datetime.now(UTC):
            raise ToolError("depart_at must be a future, timezone-aware time")
        r = await request(
            "google_routes",
            "POST",
            URL,
            timeout=TIMEOUT,
            headers={
                "X-Goog-Api-Key": key(settings.google_maps_api_key, "GOOGLE_MAPS_API_KEY"),
                "X-Goog-FieldMask": FIELDS,
            },
            json={
                "origin": _point(*origin),
                "destination": _point(*destination),
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE",
                "departureTime": depart_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        routes = ok_json(r, "google_routes").get("routes", [])
    except ToolError as exc:
        return failed("travel_time", SOURCE, query, str(exc))
    data = None
    if routes:
        seconds = float(routes[0]["duration"].rstrip("s"))
        data = {
            "minutes": round(seconds / 60, 1),
            "km": round(routes[0].get("distanceMeters", 0) / 1000, 1),
        }
    return result("travel_time", SOURCE, query, data)
