"""Tests for the map-tool experiments in experiments/tools/geo. No network: httpx.get and
httpx.post are replaced by fakes, and runs go to a temporary folder."""

import csv
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from experiments.tools.geo import collect, common, elevation, osm, places, routes, score, social

REAL_DIR = Path(common.__file__).resolve().parent
SITE = {"site_id": "site_01", "lat": 30.0, "lng": 31.0}
FAKE_KEY = "secret-key-must-not-leak"


def keys() -> common.Keys:
    k = SecretStr(FAKE_KEY)
    return common.Keys(
        google_maps_api_key=k,
        foursquare_api_key=k,
        openrouteservice_api_key=k,
        serper_api_key=k,
    )


class FakeResponse:
    def __init__(self, data: Any, status: int = 200):
        self._data = data
        self.status_code = status
        self.text = json.dumps(data)

    def json(self) -> Any:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=None)  # type: ignore[arg-type]


GOOGLE_PLACES = {
    "places": [
        {
            "id": "g1",
            "displayName": {"text": "Bean Cafe"},
            "location": {"latitude": 30.001, "longitude": 31.0},
            "rating": 4.5,
            "userRatingCount": 12,
            "businessStatus": "OPERATIONAL",
            "regularOpeningHours": {"weekdayDescriptions": ["Mon: 8-22"]},
            "primaryType": "cafe",
        },
        {
            "id": "g2",
            "displayName": {"text": "Far Cafe"},
            "location": {"latitude": 30.02, "longitude": 31.0},
            "userRatingCount": 0,
            "businessStatus": "OPERATIONAL",
        },
    ]
}
FSQ = {
    "results": [
        {
            "fsq_place_id": "f1",
            "name": "Bean Cafe Obour",
            "latitude": 30.0011,
            "longitude": 31.0,
            "categories": [{"name": "Café"}],
            "date_refreshed": "2026-01-01",
        },
        {"fsq_place_id": "f2", "name": "Other", "latitude": 30.005, "longitude": 31.0},
    ]
}


def fake_http(monkeypatch, seen: list[dict[str, Any]]) -> None:
    def respond(url: str, **kw: Any) -> FakeResponse:
        seen.append({"url": url, **kw})
        if "searchNearby" in url:
            return FakeResponse(GOOGLE_PLACES)
        if "places.googleapis.com/v1/places/" in url:
            return FakeResponse({"reviews": [{"publishTime": "2026-11-01T00:00:00Z"}]})
        if "foursquare" in url:
            return FakeResponse(FSQ)
        if "overpass" in url:
            return FakeResponse(
                {
                    "elements": [
                        {
                            "type": "way",
                            "tags": {"highway": "primary"},
                            "geometry": [{"lat": 30.0, "lon": 31.001}],
                        }
                    ]
                }
            )
        if "computeRoutes" in url:
            return FakeResponse(
                {
                    "routes": [
                        {
                            "duration": "1800s",
                            "staticDuration": "1500s",
                            "distanceMeters": 25000,
                            "legs": [
                                {"startLocation": {"latLng": {"latitude": 30.1, "longitude": 31.3}}}
                            ],
                        }
                    ]
                }
            )
        if "openrouteservice" in url or "heigit" in url:
            return FakeResponse({"routes": [{"summary": {"duration": 1440, "distance": 24000}}]})
        if "project-osrm" in url:
            return FakeResponse({"routes": [{"duration": 1380, "distance": 24500}]})
        if "elevation" in url or "opentopodata" in url:
            n = len(kw["params"]["locations"].split("|"))
            return FakeResponse(
                {"status": "OK", "results": [{"elevation": 100.0 + i % 3} for i in range(n)]}
            )
        if "serper" in url:
            return FakeResponse(
                {
                    "organic": [
                        {
                            "link": "https://www.facebook.com/groups/obour/posts/1",
                            "title": "Obour cafes",
                            "snippet": "new cafe",
                            "date": "3 days ago",
                        },
                        {"link": "https://www.instagram.com/p/x", "title": "Padel", "snippet": "x"},
                    ]
                }
            )
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(httpx, "post", lambda url, **kw: respond(url, **kw))
    monkeypatch.setattr(httpx, "get", lambda url, **kw: respond(url, **kw))


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    shutil.copytree(REAL_DIR / "cases", tmp_path / "cases")
    return tmp_path


# --- common --------------------------------------------------------------------------


def test_run_call_statuses() -> None:
    ok = common.run_call(common.Call("t", "p", "c", {}, lambda p: ({"a": 1}, 3)))
    empty = common.run_call(common.Call("t", "p", "c", {}, lambda p: ({}, 0)))

    def boom(p: dict[str, Any]) -> tuple[Any, int]:
        raise RuntimeError("down")

    err = common.run_call(common.Call("t", "p", "c", {}, boom))
    assert (ok["status"], empty["status"], err["status"]) == ("ok", "empty", "error")
    assert "down" in err["error"]


def test_save_run_never_overwrites(tmp_path: Path) -> None:
    payload = {"provider": "google", "case": "x"}
    a = common.save_run(tmp_path, payload)
    b = common.save_run(tmp_path, payload)
    assert a != b and a.exists() and b.exists()


def test_haversine_and_offset() -> None:
    lat, lng = common.offset_point(30.0, 31.0, 1000, 0)
    assert abs(common.haversine_m(30.0, 31.0, lat, lng) - 1000) < 2


# --- places --------------------------------------------------------------------------


def test_places_items_and_score(monkeypatch) -> None:
    payload = {
        "provider": "google",
        "params": {"lat": 30.0, "lng": 31.0},
        "meta": {"category": "cafe", "radius": 1000},
        "raw": GOOGLE_PLACES,
    }
    row = places.score_file(payload)
    assert row["n_places"] == 2
    assert row["n_within_radius"] == 1  # the second one is ~2.2 km away
    assert row["n_with_reviews"] == 1 and row["n_with_hours"] == 1


def test_places_overlap_matches_close_same_name() -> None:
    g = places.items({"provider": "google", "params": SITE, "raw": GOOGLE_PLACES})
    f = places.items({"provider": "foursquare", "params": SITE, "raw": FSQ})
    assert places.overlap(g, f) == {"both": 1, "only_google": 1, "only_foursquare": 1}


def test_places_followup_picks_places_with_reviews() -> None:
    res = [{"provider": "google", "status": "ok", "params": SITE, "raw": GOOGLE_PLACES}]
    calls = places.followup_calls(res, {"details_max": 5}, keys())
    assert [c.params["place_id"] for c in calls] == ["g1"]


# --- osm -----------------------------------------------------------------------------


def test_osm_queries_and_road_score() -> None:
    assert "is_in(30.0,31.0)" in osm.overpass_query("pin_area", 30.0, 31.0, 0)
    assert "out count" in osm.overpass_query("buildings", 30.0, 31.0, 500)
    with pytest.raises(ValueError):
        osm.overpass_query("nope", 30.0, 31.0, 1)
    payload = {
        "params": {"kind": "major_roads", "radius": 3000, "lat": 30.0, "lng": 31.0},
        "raw": {
            "elements": [
                {
                    "tags": {"highway": "trunk", "name": "Suez Road"},
                    "geometry": [{"lat": 30.0, "lon": 31.002}],
                    "timestamp": "2026-01-01T00:00:00Z",
                },
                {"tags": {"highway": "residential"}, "geometry": [{"lat": 30.0, "lon": 31.0001}]},
            ]
        },
    }
    row = osm.score_file(payload)
    assert row["nearest_major_name"] == "Suez Road"
    assert 150 < row["nearest_major_m"] < 250


# --- routes --------------------------------------------------------------------------


def test_departure_times_are_future_and_cairo() -> None:
    now = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)  # a Saturday
    times = routes.departure_times([{"label": "sun", "weekday": 6, "time": "08:00"}], now)
    assert times[0]["utc"] == "2026-11-29T06:00:00Z"


def test_routes_score_and_followups() -> None:
    raw = {
        "routes": [
            {
                "duration": "1800s",
                "staticDuration": "1500s",
                "distanceMeters": 25000,
                "legs": [{"startLocation": {"latLng": {"latitude": 30.1, "longitude": 31.3}}}],
            }
        ]
    }
    res = [
        {
            "provider": "google",
            "status": "ok",
            "raw": raw,
            "params": {"destination": {"lat": 30.0, "lng": 31.0}},
            "meta": {"landmark": "airport", "direction": "to_site"},
        }
    ]
    row = routes.score_file({"provider": "google", "raw": raw, "meta": res[0]["meta"]})
    assert (row["minutes"], row["no_traffic_minutes"], row["km"]) == (30.0, 25.0, 25.0)
    calls = routes.followup_calls(res, {}, keys())
    assert {c.provider for c in calls} == {"openrouteservice", "osrm"} and len(calls) == 4


# --- elevation -----------------------------------------------------------------------


def test_elevation_grid_and_slope() -> None:
    cases = {"grid_n": 3, "grid_spacing_m": 100, "ring_m": [1000]}
    pts = elevation.grid_points(SITE, cases)
    assert len(pts) == 9 + 8
    hs = [100.0 + pt.get("col", 0) * 2 for pt in pts]  # rises 2 m per 100 m eastwards
    payload = {
        "params": {"points": pts},
        "meta": {"grid_spacing_m": 100},
        "raw": {"results": [{"elevation": h} for h in hs]},
    }
    row = elevation.score_file(payload)
    assert row["site_relief_m"] == 4.0 and row["max_slope_pct"] == 2.0


def test_google_elevation_error_hides_key(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeResponse({"x": 1}, status=403))
    res = common.run_call(
        common.Call(
            "elevation",
            "google",
            "grid",
            {"points": [{"lat": 1, "lng": 2}]},
            elevation.google_elevation(keys()),
        )
    )
    assert res["status"] == "error" and FAKE_KEY not in res["error"]


# --- social --------------------------------------------------------------------------


def test_social_dates_and_score() -> None:
    now = datetime(2026, 11, 28, tzinfo=UTC)
    assert social.parse_date("3 days ago", now) == datetime(2026, 11, 25, tzinfo=UTC)
    assert social.parse_date("Nov 5, 2025", now) == datetime(2025, 11, 5, tzinfo=UTC)
    assert social.parse_date("garbage", now) is None
    payload = {
        "meta": {"query_id": "q", "variant": "all"},
        "raw": {
            "organic": [
                {"link": "https://m.facebook.com/a", "title": "العبور", "date": "2 weeks ago"},
                {"link": "https://example.com/b", "title": "x"},
            ]
        },
    }
    row = social.score_file(payload, {"facebook": "facebook.com"}, ["العبور"], now)
    assert row["by_platform"] == "facebook=1; other=1"
    assert row["n_mentions_place"] == 1 and row["n_last_12_months"] == 1


# --- end to end ----------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["places", "osm", "routes", "elevation", "social"])
def test_collect_then_score(tool: str, base_dir: Path, monkeypatch) -> None:
    seen: list[dict[str, Any]] = []
    fake_http(monkeypatch, seen)
    results = collect.collect_tool(
        tool, "site_01", "v1", "test", keys(), base_dir=base_dir, pause=0
    )
    assert results and all(r["status"] != "error" for r in results), [
        r["error"] for r in results if r["error"]
    ]
    files = list((base_dir / "runs" / tool).rglob("*.json"))
    assert len(files) == len(results)
    assert all(FAKE_KEY not in f.read_text(encoding="utf-8") for f in files)
    n, s = score.score_tool(tool, base_dir)
    assert n == len(files) and s > 0
    with (base_dir / f"summary_{tool}.csv").open(encoding="utf-8") as f:
        assert list(csv.DictReader(f))


def test_overpass_sends_descriptive_user_agent(monkeypatch) -> None:
    seen: list[dict[str, Any]] = []
    fake_http(monkeypatch, seen)
    calls = osm.build_calls(
        SITE,
        {
            "endpoints": {"m": "https://overpass.x/api"},
            "cases": [{"kind": "roads", "radius_m": 100}],
        },
        keys(),
    )
    common.run_call(calls[0])
    ua = seen[0]["headers"]["User-Agent"]
    assert "gp-backend" in ua and "httpx" not in ua


def test_only_reruns_followups_from_saved_runs(base_dir: Path, monkeypatch) -> None:
    seen: list[dict[str, Any]] = []
    fake_http(monkeypatch, seen)
    collect.collect_tool("routes", "site_01", "v1", "first", keys(), base_dir=base_dir, pause=0)
    seen.clear()
    again = collect.collect_tool(
        "routes",
        "site_01",
        "v1",
        "ors only",
        keys(),
        base_dir=base_dir,
        pause=0,
        only=["openrouteservice"],
    )
    assert again and {r["provider"] for r in again} == {"openrouteservice"}
    assert all("heigit" in s["url"] for s in seen)  # Google was not called again


def test_social_titles_match_across_redirect_links() -> None:
    a = {
        "meta": {},
        "raw": {
            "organic": [
                {"link": "https://www.google.com/goto?url=AAA", "title": "Cafe X — العبور!"}
            ]
        },
    }
    b = {
        "meta": {},
        "raw": {
            "organic": [{"link": "https://www.google.com/goto?url=BBB", "title": "cafe x  العبور"}]
        },
    }
    ta = social.score_file(a, {}, [])["titles"]
    tb = social.score_file(b, {}, [])["titles"]
    assert ta == tb


# --- osm v3: local cache -------------------------------------------------------------

OSM_XML = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="30.000" lon="31.000" version="1" timestamp="2025-01-01T00:00:00Z"/>
  <node id="2" lat="30.000" lon="31.010" version="1" timestamp="2025-01-01T00:00:00Z"/>
  <node id="3" lat="29.995" lon="30.995" version="1"/>
  <node id="4" lat="29.995" lon="31.005" version="1"/>
  <node id="5" lat="30.005" lon="31.005" version="1"/>
  <node id="6" lat="30.005" lon="30.995" version="1"/>
  <node id="7" lat="30.0010" lon="31.0010" version="1"/>
  <node id="8" lat="30.0010" lon="31.0012" version="1"/>
  <node id="9" lat="30.0012" lon="31.0012" version="1"/>
  <node id="10" lat="30.0002" lon="31.0003" version="1" timestamp="2026-06-01T00:00:00Z">
    <tag k="amenity" v="cafe"/><tag k="name" v="Bean"/>
  </node>
  <node id="11" lat="35.0" lon="35.0" version="1"><tag k="amenity" v="cafe"/></node>
  <way id="100" version="1" timestamp="2025-01-01T00:00:00Z">
    <nd ref="1"/><nd ref="2"/><tag k="highway" v="trunk"/><tag k="name" v="Suez Road"/>
  </way>
  <way id="101" version="1">
    <nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="6"/><nd ref="3"/>
    <tag k="landuse" v="residential"/>
  </way>
  <way id="102" version="1">
    <nd ref="7"/><nd ref="8"/><nd ref="9"/><nd ref="7"/><tag k="building" v="yes"/>
  </way>
  <way id="103" version="1"><nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="6"/><nd ref="3"/></way>
  <relation id="200" version="1">
    <member type="way" ref="103" role="outer"/>
    <tag k="type" v="boundary"/><tag k="boundary" v="administrative"/>
    <tag k="admin_level" v="8"/><tag k="name" v="Test City"/>
  </relation>
</osm>
"""
BOX = {"min_lat": 29.9, "max_lat": 30.1, "min_lng": 30.9, "max_lng": 31.1}


@pytest.fixture
def osm_cache(tmp_path: Path) -> dict[str, Any]:
    pytest.importorskip("osmium")
    from experiments.tools.geo import osm_data

    src = tmp_path / "test.osm"
    src.write_text(OSM_XML, encoding="utf-8")
    cache = osm_data.build_cache(src, BOX)
    path = tmp_path / "cache.json.gz"
    osm_data.write_cache(cache, path)
    return osm_data.load_cache(path)


def test_cache_keeps_only_the_box(osm_cache: dict[str, Any]) -> None:
    counts = osm_cache["meta"]["counts"]
    assert counts == {"roads": 1, "areas": 2, "buildings": 1, "pois": 1}  # cafe at 35,35 dropped


def test_local_queries_answer_like_overpass(osm_cache: dict[str, Any]) -> None:
    lat, lng = 30.0003, 31.0002
    roads = osm.local_query(osm_cache, "major_roads", lat, lng, 3000)
    assert roads[0]["tags"]["name"] == "Suez Road" and roads[0]["geometry"]
    names = {e["tags"].get("name") for e in osm.local_query(osm_cache, "pin_area", lat, lng, 0)}
    assert "Test City" in names
    landuse = osm.local_query(osm_cache, "landuse", lat, lng, 1000)
    assert [e["tags"]["landuse"] for e in landuse] == ["residential"]
    assert osm.local_query(osm_cache, "buildings", lat, lng, 500)[0]["tags"]["total"] == "1"
    assert len(osm.local_query(osm_cache, "pois", lat, lng, 1000)) == 1
    payload = {
        "params": {"kind": "major_roads", "radius": 3000, "lat": lat, "lng": lng},
        "raw": {"elements": roads},
    }
    row = osm.score_file(payload)
    assert row["nearest_major_name"] == "Suez Road" and row["nearest_major_m"] < 40


def test_distance_to_line_uses_segments() -> None:
    # a point 100 m north of the middle of a 2 km east-west road: vertices are 1 km away
    lat, lng = common.offset_point(30.0, 31.01, 100, 0)
    d = osm.dist_to_line_m(lat, lng, [[30.0, 31.0], [30.0, 31.02]])
    assert 95 < d < 105
