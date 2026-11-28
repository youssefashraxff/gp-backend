"""Routes: drive times between the site and the places its customers come from.

Google Routes is asked with live-traffic prediction at several times of a future day, in
both directions. Google also resolves each landmark's address to a point; those points are
then sent to OpenRouteService and the public OSRM server, which have no traffic, so they
can be compared with Google's no-traffic time (`staticDuration`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx

from experiments.tools.geo.common import POLITE_HEADERS, TIMEOUT_SECONDS, Call, Keys, require

GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
GOOGLE_ROUTES_FIELDS = (
    "routes.duration,routes.staticDuration,routes.distanceMeters,"
    "routes.legs.startLocation,routes.legs.endLocation"
)
# api.openrouteservice.org was shut down on 2026-09-28 (410 Gone); HeiGIT moved it here.
ORS_URL = "https://api.heigit.org/openrouteservice/v2/directions/driving-car"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{a};{b}?overview=false"


def cairo_tz() -> Any:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Africa/Cairo")
    except Exception:  # noqa: BLE001 (no tz database, e.g. Windows without tzdata)
        return timezone(timedelta(hours=2))


def next_weekday(weekday: int, now: datetime | None = None) -> datetime:
    """The date of the next `weekday` (Mon=0 .. Sun=6) at least 1 day ahead, Cairo time."""
    tz = cairo_tz()
    today = (now or datetime.now(UTC)).astimezone(tz).date()
    days = (weekday - today.weekday()) % 7 or 7
    d = today + timedelta(days=days)
    return datetime(d.year, d.month, d.day, tzinfo=tz)


def departure_times(slots: list[dict[str, Any]], now: datetime | None = None) -> list[dict]:
    """Turn {"label", "weekday", "time": "HH:MM"} into future UTC departure times."""
    out = []
    for s in slots:
        day = next_weekday(int(s["weekday"]), now)
        hh, mm = (int(x) for x in s["time"].split(":"))
        local = day.replace(hour=hh, minute=mm)
        out.append(
            {
                "label": s["label"],
                "local": local.isoformat(),
                "utc": local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    return out


def _waypoint(w: dict[str, Any]) -> dict[str, Any]:
    if "address" in w:
        return {"address": w["address"]}
    return {"location": {"latLng": {"latitude": w["lat"], "longitude": w["lng"]}}}


def google_route(keys: Keys) -> Any:
    key = require(keys.google_maps_api_key, "GOOGLE_MAPS_API_KEY")

    def fn(p: dict[str, Any]) -> tuple[Any, int]:
        body = {
            "origin": _waypoint(p["origin"]),
            "destination": _waypoint(p["destination"]),
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "departureTime": p["departure_utc"],
            "languageCode": "en",
            "units": "METRIC",
        }
        r = httpx.post(
            GOOGLE_ROUTES_URL,
            json=body,
            headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": GOOGLE_ROUTES_FIELDS},
            timeout=TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        raw = r.json()
        return raw, len(raw.get("routes", []))

    return fn


def ors_route(keys: Keys) -> Any:
    key = require(keys.openrouteservice_api_key, "OPENROUTESERVICE_API_KEY")

    def fn(p: dict[str, Any]) -> tuple[Any, int]:
        o, d = p["origin"], p["destination"]
        r = httpx.post(
            ORS_URL,
            json={"coordinates": [[o["lng"], o["lat"]], [d["lng"], d["lat"]]]},
            headers={"Authorization": key},
            timeout=TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        raw = r.json()
        return raw, len(raw.get("routes", []))

    return fn


def osrm_route() -> Any:
    def fn(p: dict[str, Any]) -> tuple[Any, int]:
        o, d = p["origin"], p["destination"]
        url = OSRM_URL.format(a=f"{o['lng']},{o['lat']}", b=f"{d['lng']},{d['lat']}")
        r = httpx.get(url, headers=POLITE_HEADERS, timeout=TIMEOUT_SECONDS)
        r.raise_for_status()
        raw = r.json()
        return raw, len(raw.get("routes", []))

    return fn


def build_calls(
    site: dict[str, Any], cases: dict[str, Any], keys: Keys, now: datetime | None = None
) -> list[Call]:
    """Google calls only; the no-traffic providers need Google's resolved landmark points."""
    pin = {"lat": site["lat"], "lng": site["lng"]}
    calls: list[Call] = []
    for lm in cases["landmarks"]:
        place = {"address": lm["address"]}
        for t in departure_times(cases["departures"], now):
            for direction, (o, d) in (("to_site", (place, pin)), ("from_site", (pin, place))):
                case = f"{lm['id']}_{direction}_{t['label']}"
                params = {"origin": o, "destination": d, "departure_utc": t["utc"]}
                meta = {
                    "landmark": lm["id"],
                    "direction": direction,
                    "slot": t["label"],
                    "local": t["local"],
                }
                calls.append(Call("routes", "google", case, params, google_route(keys), meta))
    return calls


def landmark_points(results: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Where Google placed each landmark (start of the to_site routes)."""
    points: dict[str, dict[str, float]] = {}
    for res in results:
        meta = res.get("meta") or {}
        if res["provider"] != "google" or res["status"] != "ok":
            continue
        if meta.get("direction") != "to_site" or meta["landmark"] in points:
            continue
        legs = res["raw"]["routes"][0].get("legs") or []
        ll = ((legs[0].get("startLocation") or {}).get("latLng") or {}) if legs else {}
        if "latitude" in ll:
            points[meta["landmark"]] = {"lat": ll["latitude"], "lng": ll["longitude"]}
    return points


def followup_calls(results: list[dict[str, Any]], cases: dict[str, Any], keys: Keys) -> list[Call]:
    site_pin = None
    for res in results:
        if res["provider"] == "google" and (res.get("meta") or {}).get("direction") == "to_site":
            site_pin = res["params"]["destination"]
            break
    if site_pin is None:
        return []
    calls: list[Call] = []
    providers = cases.get("no_traffic_providers", ["openrouteservice", "osrm"])
    for lm_id, pt in landmark_points(results).items():
        for direction, (o, d) in (("to_site", (pt, site_pin)), ("from_site", (site_pin, pt))):
            params = {"origin": o, "destination": d}
            meta = {"landmark": lm_id, "direction": direction, "slot": "no_traffic"}
            case = f"{lm_id}_{direction}"
            if "openrouteservice" in providers:
                calls.append(
                    Call("routes", "openrouteservice", case, params, ors_route(keys), meta)
                )
            if "osrm" in providers:
                calls.append(Call("routes", "osrm", case, params, osrm_route(), meta))
    return calls


# ---------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------


def _seconds(value: Any) -> float | None:
    """Google gives durations as "1234s"; the others as numbers."""
    if value is None:
        return None
    if isinstance(value, str):
        return float(value.rstrip("s"))
    return float(value)


def score_file(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("meta") or {}
    raw = payload.get("raw") or {}
    route = (raw.get("routes") or [{}])[0] if raw.get("routes") else {}
    duration = static = distance = None
    if payload["provider"] == "google":
        duration = _seconds(route.get("duration"))
        static = _seconds(route.get("staticDuration"))
        distance = route.get("distanceMeters")
    elif payload["provider"] == "openrouteservice":
        summary = route.get("summary") or {}
        duration = _seconds(summary.get("duration"))
        distance = summary.get("distance")
    elif payload["provider"] == "osrm":
        duration = _seconds(route.get("duration"))
        distance = route.get("distance")
    return {
        "landmark": meta.get("landmark"),
        "direction": meta.get("direction"),
        "slot": meta.get("slot"),
        "local_time": meta.get("local"),
        "minutes": round(duration / 60, 1) if duration is not None else None,
        "no_traffic_minutes": round(static / 60, 1) if static is not None else None,
        "km": round(float(distance) / 1000, 1) if distance is not None else None,
    }
