"""Shared helpers for the map-tool experiments: keys, calling, saving, distances.

Nothing here calls an LLM. Each tool module (places, osm, routes, elevation, social) builds
its calls from a case file, `collect.py` runs them and saves every raw response, and
`score.py` measures the saved files afterwards (scoring never calls an API).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parents[2]
SITES_DIR = REPO_DIR / "experiments" / "test_sites"
TIMEOUT_SECONDS = 40
PAUSE_SECONDS = 1.0  # between calls; OpenTopoData and the public Overpass/OSRM need it

STATUS_OK = "ok"
STATUS_EMPTY = "empty"  # the call worked but returned nothing
STATUS_ERROR = "error"


class Keys(BaseSettings):
    """API keys from the environment or `.env`. SecretStr keeps them out of prints and logs."""

    model_config = SettingsConfigDict(env_file=REPO_DIR / ".env", extra="ignore")

    google_maps_api_key: SecretStr | None = None
    foursquare_api_key: SecretStr | None = None
    openrouteservice_api_key: SecretStr | None = None
    serper_api_key: SecretStr | None = None


def require(key: SecretStr | None, name: str) -> str:
    if key is None or not key.get_secret_value():
        raise RuntimeError(f"{name} is not set; add it to .env")
    return key.get_secret_value()


@dataclass
class Call:
    """One planned API call. `fn` does the request and returns (raw_response, n_items)."""

    tool: str  # places, osm, routes, elevation, social
    provider: str  # google, foursquare, overpass_main, ...
    case: str  # short id of what is asked, e.g. "cafe_r1000"
    params: dict[str, Any]
    fn: Callable[[dict[str, Any]], tuple[Any, int]]
    meta: dict[str, Any] = field(default_factory=dict)


def run_call(call: Call) -> dict[str, Any]:
    """Run one call. Never raises: a failure is saved with status `error`."""
    start = time.perf_counter()
    raw: Any = None
    n_items = 0
    error = ""
    try:
        raw, n_items = call.fn(dict(call.params))
    except Exception as exc:  # noqa: BLE001 (any failure is a result to record, not a crash)
        error = f"{type(exc).__name__}: {exc}"
    if error:
        status = STATUS_ERROR
    elif n_items == 0:
        status = STATUS_EMPTY
    else:
        status = STATUS_OK
    return {
        "tool": call.tool,
        "provider": call.provider,
        "case": call.case,
        "params": call.params,
        "meta": call.meta,
        "status": status,
        "n_items": n_items,
        "error": error,
        "seconds": round(time.perf_counter() - start, 3),
        "raw": raw,
    }


def runs_dir(tool: str, case_version: str, site_id: str, base_dir: Path = BASE_DIR) -> Path:
    return base_dir / "runs" / tool / case_version / site_id


def save_run(folder: Path, payload: dict[str, Any]) -> Path:
    """Write a new run file named by time first. Mode "x" refuses to overwrite."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    name = f"{stamp}__{payload['provider']}__{payload['case']}.json"
    path = folder / name
    with path.open("x", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    return path


def load_site(site_id: str, sites_dir: Path = SITES_DIR) -> dict[str, Any]:
    path = sites_dir / f"{site_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"No test site {site_id} at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_cases(tool: str, version: str, base_dir: Path = BASE_DIR) -> dict[str, Any]:
    path = base_dir / "cases" / f"{tool}_{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"No cases '{version}' for {tool} at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance in metres between two points on the earth (good to well under 1 %)."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def offset_point(lat: float, lng: float, north_m: float, east_m: float) -> tuple[float, float]:
    """The point `north_m` north and `east_m` east of (lat, lng)."""
    dlat = north_m / 111_320.0
    dlng = east_m / (111_320.0 * math.cos(math.radians(lat)))
    return round(lat + dlat, 7), round(lng + dlng, 7)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def age_days(iso: str | None, now: datetime | None = None) -> float | None:
    """Days between an ISO date/time and now; None if missing or unreadable."""
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return round(((now or datetime.now(UTC)) - when).total_seconds() / 86400, 1)
