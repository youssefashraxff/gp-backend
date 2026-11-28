"""Shared research tools (app/shared/tools). Recorded API responses from the A3 experiment
(tests/fixtures/tools), served through httpx.MockTransport: no network."""

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.shared.settings import settings
from app.shared.tools import (
    ToolRun,
    base,
    elevation,
    osm,
    osm_around,
    place_details,
    places_nearby,
    travel_time,
    web_search,
)

FIXTURES = Path(__file__).parent / "fixtures" / "tools"
KEY = "test-key-must-not-leak"
FUTURE = datetime.now(UTC) + timedelta(days=1)


def recorded(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def setup(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_maps_api_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "serper_api_key", SecretStr(KEY))
    monkeypatch.setattr(base, "BACKOFF_SECONDS", 0)


def serve(monkeypatch, *responses: Any) -> list[httpx.Request]:
    """Answer requests in order: a dict is JSON 200, an int is that status, "timeout" times
    out. The last answer repeats."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = responses[min(len(seen), len(responses)) - 1]
        if answer == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if isinstance(answer, int):
            return httpx.Response(answer, text="error body")
        return httpx.Response(200, json=answer)

    monkeypatch.setattr(base, "TRANSPORT", httpx.MockTransport(handler))
    return seen


# One call per client, with the recorded response it should parse.
CLIENTS = {
    "places_nearby": (lambda: places_nearby(30.19, 31.46, 1000, ["cafe"]), "places_nearby"),
    "place_details": (lambda: place_details("abc"), "place_details"),
    "travel_time": (lambda: travel_time((30.12, 31.40), (30.32, 31.56), FUTURE), "routes"),
    "elevation": (lambda: elevation([(30.32, 31.55)]), "elevation"),
    "web_search": (lambda: web_search("كافيهات العبور الجديدة", lang="ar"), "serper"),
}


@pytest.mark.parametrize("name", CLIENTS)
async def test_parses_recorded_response(name: str, monkeypatch) -> None:
    call, fixture = CLIENTS[name]
    serve(monkeypatch, recorded(fixture))
    res = await call()
    assert res.status == "ok", res.error
    assert res.tool == name and res.source and res.retrieved_at


@pytest.mark.parametrize("name", CLIENTS)
async def test_times_out_retries_then_gives_up_cleanly(name: str, monkeypatch) -> None:
    seen = serve(monkeypatch, "timeout")
    res = await CLIENTS[name][0]()
    assert res.status == "error" and "gave up after 3 attempts" in res.error
    assert len(seen) == 3


@pytest.mark.parametrize("name", CLIENTS)
async def test_retries_429_then_succeeds(name: str, monkeypatch) -> None:
    call, fixture = CLIENTS[name]
    seen = serve(monkeypatch, 429, 503, recorded(fixture))
    assert (await call()).status == "ok" and len(seen) == 3


@pytest.mark.parametrize("name", CLIENTS)
async def test_client_error_is_not_retried_and_hides_the_key(name: str, monkeypatch) -> None:
    seen = serve(monkeypatch, 403)
    res = await CLIENTS[name][0]()
    assert res.status == "error" and len(seen) == 1 and KEY not in res.error


async def test_missing_key_fails_without_calling(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_maps_api_key", None)
    seen = serve(monkeypatch, {})
    res = await places_nearby(30.0, 31.0, 1000, ["cafe"])
    assert res.status == "error" and "GOOGLE_MAPS_API_KEY" in res.error and not seen


async def test_places_fields_and_cap(monkeypatch) -> None:
    seen = serve(monkeypatch, recorded("places_nearby"))
    res = await places_nearby(30.19, 31.46, 1000, ["cafe"])
    first = res.data[0]
    assert first["name"] and first["lat"] and "review_count" in first
    assert seen[0].headers["X-Goog-FieldMask"].startswith("places.id")
    assert not res.capped
    twenty = {"places": recorded("places_nearby")["places"][:1] * 20}
    serve(monkeypatch, twenty)
    assert (await places_nearby(30.19, 31.46, 3000, ["cafe"])).capped


async def test_place_details_keeps_review_dates(monkeypatch) -> None:
    serve(monkeypatch, recorded("place_details"))
    res = await place_details("abc")
    assert res.data["reviews"] and res.data["reviews"][0]["published_at"]


async def test_travel_time_needs_a_future_departure(monkeypatch) -> None:
    serve(monkeypatch, recorded("routes"))
    res = await travel_time((30.12, 31.40), (30.32, 31.56), FUTURE)
    assert res.data == {"minutes": 45.9, "km": 44.8}
    seen = serve(monkeypatch, recorded("routes"))
    past = await travel_time((30.12, 31.40), (30.32, 31.56), datetime.now(UTC))
    assert past.status == "error" and not seen


async def test_elevation_limits_points(monkeypatch) -> None:
    serve(monkeypatch, recorded("elevation"))
    res = await elevation([(30.32, 31.55)])
    assert res.data[0]["elevation_m"] == 93.8 and res.data[0]["resolution_m"] == 9.5
    assert (await elevation([(30.0, 31.0)] * 513)).status == "error"


async def test_web_search_site_filter_and_dates(monkeypatch) -> None:
    seen = serve(monkeypatch, recorded("serper"))
    await web_search("padel", sites=["facebook.com", "x.com"], months=24)
    body = json.loads(seen[0].content)
    assert body["q"] == "padel (site:facebook.com OR site:x.com)" and body["gl"] == "eg"
    assert body["tbs"].startswith("cdr:1,cd_min:")


async def test_tool_run_caches_and_logs(monkeypatch) -> None:
    run = ToolRun()
    seen = serve(monkeypatch, recorded("elevation"))
    a = await run.call(elevation, points=[(30.32, 31.55)])
    b = await run.call(elevation, points=[(30.32, 31.55)])
    assert a is b and len(seen) == 1
    assert [e["cached"] for e in run.log] == [False, True]
    serve(monkeypatch, 500)
    await run.call(place_details, place_id="x")
    assert run.log[-1]["status"] == "error" and len(run.cache) == 1  # errors are not cached


# --- OSM local cache -----------------------------------------------------------------

OSM_XML = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="30.000" lon="31.000" version="1" timestamp="2025-01-01T00:00:00Z"/>
  <node id="2" lat="30.000" lon="31.010" version="1"/>
  <node id="3" lat="29.995" lon="30.995" version="1"/>
  <node id="4" lat="29.995" lon="31.005" version="1"/>
  <node id="5" lat="30.005" lon="31.005" version="1"/>
  <node id="6" lat="30.005" lon="30.995" version="1"/>
  <node id="10" lat="30.0002" lon="31.0003" version="1">
    <tag k="amenity" v="cafe"/><tag k="name" v="Bean"/>
  </node>
  <node id="11" lat="35.0" lon="35.0" version="1"><tag k="amenity" v="cafe"/></node>
  <way id="100" version="1">
    <nd ref="1"/><nd ref="2"/><tag k="highway" v="trunk"/><tag k="name" v="Suez Road"/>
  </way>
  <way id="101" version="1">
    <nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="6"/><nd ref="3"/>
    <tag k="landuse" v="residential"/>
  </way>
  <way id="103" version="1"><nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="6"/><nd ref="3"/></way>
  <relation id="200" version="1">
    <member type="way" ref="103" role="outer"/>
    <tag k="type" v="boundary"/><tag k="boundary" v="administrative"/>
    <tag k="name" v="Test City"/>
  </relation>
</osm>
"""
BOXES = {"test": (29.9, 30.9, 30.1, 31.1)}


@pytest.fixture
def osm_cache(tmp_path: Path, monkeypatch) -> Path:
    pytest.importorskip("osmium")
    src = tmp_path / "test.osm"
    src.write_text(OSM_XML, encoding="utf-8")
    cache = osm.build_cache(src, BOXES)
    path = tmp_path / "osm_cache.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(cache, f)
    monkeypatch.setattr(settings, "osm_cache_path", path)
    return path


async def test_osm_build_keeps_only_the_boxes(osm_cache: Path) -> None:
    meta = osm.load(osm_cache)["meta"]  # type: ignore[index]
    assert meta["counts"] == {"roads": 1, "areas": 2, "pois": 1}  # cafe at 35,35 dropped


async def test_osm_around_answers_from_the_cache(osm_cache: Path) -> None:
    res = await osm_around(30.0003, 31.0002)
    assert res.status == "ok" and "local copy" in res.source
    data = res.data
    assert data["nearest_major_road"]["name"] == "Suez Road"
    assert data["nearest_major_road"]["distance_m"] < 40
    assert data["landuse"] == {"residential": 1} and data["pois"][0]["name"] == "Bean"
    assert {a["name"] for a in data["inside"]} >= {"Test City"}


async def test_osm_outside_coverage_or_no_cache_is_an_error(osm_cache: Path, monkeypatch) -> None:
    assert (await osm_around(26.0, 33.0)).error == "outside the OSM cache's coverage"
    monkeypatch.setattr(settings, "osm_cache_path", osm_cache.parent / "missing.json.gz")
    assert "no OSM cache" in (await osm_around(30.0, 31.0)).error


def test_distance_uses_segments_not_vertices() -> None:
    lat = 30.0 + 100 / 111_320.0  # 100 m north of the middle of a 2 km road
    assert 95 < osm.distance_m(lat, 31.01, [[30.0, 31.0], [30.0, 31.02]]) < 105
