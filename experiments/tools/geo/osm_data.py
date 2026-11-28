"""Build a local OpenStreetMap cache for the OSM experiment (osm v3).

The public Overpass servers failed 41 of 48 calls in osm v2, so v3 answers the same
questions from a local copy of the data instead:

1. take the Egypt file (`egypt-latest.osm.pbf` from Geofabrik): a file you pass with
   `--source`, or one already in `data/`, or else it is downloaded and its checksum checked
2. read it once and keep only what the questions need inside a box (case file `box`):
   roads with their shape, land-use / boundary / place areas with their outline, buildings
   as one point each, and points of interest
3. write that to `data/osm_cache_<cases version>.json.gz` (git-ignored) with the data's date
4. with `--delete-source`, delete the big Egypt file afterwards

Run:
    python -m experiments.tools.geo.osm_data --cases v3 --source ~/Downloads/egypt-latest.osm.pbf
    python -m experiments.tools.geo.osm_data --cases v3 --delete-source
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from experiments.tools.geo.common import BASE_DIR, POLITE_HEADERS, load_cases

DATA_DIR = BASE_DIR / "data"
EGYPT_URL = "https://download.geofabrik.de/africa/egypt-latest.osm.pbf"

ROAD_TAGS = ("highway", "name", "name:en", "ref")
AREA_KEYS = ("landuse", "boundary", "place")
AREA_TAGS = (*AREA_KEYS, "admin_level", "name", "name:en", "type")
POI_KEYS = ("amenity", "shop", "leisure")
POI_TAGS = (*POI_KEYS, "name", "name:en", "cuisine", "brand")


def cache_path(version: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"osm_cache_{version}.json.gz"


# ---------------------------------------------------------------------------------------
# Getting the Egypt file
# ---------------------------------------------------------------------------------------


def find_source(source: str | None, data_dir: Path = DATA_DIR) -> Path | None:
    """The file to read: --source if given, else an .osm.pbf already in data/."""
    if source:
        path = Path(source).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"--source {path} does not exist")
        return path
    found = sorted(data_dir.glob("*.osm.pbf")) if data_dir.exists() else []
    return found[0] if found else None


def md5_of(path: Path) -> str:
    h = hashlib.md5()  # noqa: S324 (Geofabrik publishes MD5; it checks the download, not security)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str = EGYPT_URL, data_dir: Path = DATA_DIR) -> Path:
    """Download the file and check it against Geofabrik's published MD5."""
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / url.rsplit("/", 1)[-1]
    part = target.with_suffix(target.suffix + ".part")
    with httpx.stream("GET", url, headers=POLITE_HEADERS, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with part.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  downloading {done / 1e6:.0f}/{total / 1e6:.0f} MB", end="")
    print()
    expected = httpx.get(
        url + ".md5", headers=POLITE_HEADERS, follow_redirects=True, timeout=60
    ).text.split()[0]
    actual = md5_of(part)
    if actual != expected:
        part.unlink()
        raise RuntimeError(f"checksum mismatch ({actual} != {expected}); download again")
    part.rename(target)
    return target


# ---------------------------------------------------------------------------------------
# Reading it once into a small cache
# ---------------------------------------------------------------------------------------


def _subset(tags: Any, keys: tuple[str, ...]) -> dict[str, str]:
    return {k: tags[k] for k in keys if k in tags}


def _ts(obj: Any) -> str | None:
    try:
        return obj.timestamp.isoformat()
    except Exception:  # noqa: BLE001 (files without timestamps)
        return None


def _bbox(coords: list[list[float]]) -> list[float]:
    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    return [min(lats), min(lngs), max(lats), max(lngs)]


def _overlaps(bbox: list[float], box: dict[str, float]) -> bool:
    return not (
        bbox[2] < box["min_lat"]
        or bbox[0] > box["max_lat"]
        or bbox[3] < box["min_lng"]
        or bbox[1] > box["max_lng"]
    )


def build_cache(source: Path, box: dict[str, float]) -> dict[str, Any]:
    """One pass over the file (two for areas, done by osmium) keeping what is in the box."""
    import osmium  # experiment-only dependency
    import osmium.io
    import osmium.osm

    def in_box(lat: float, lng: float) -> bool:
        return box["min_lat"] <= lat <= box["max_lat"] and box["min_lng"] <= lng <= box["max_lng"]

    out: dict[str, list[Any]] = {"roads": [], "areas": [], "buildings": [], "pois": []}

    class Handler(osmium.SimpleHandler):
        def node(self, n: Any) -> None:
            if not any(k in n.tags for k in POI_KEYS):
                return
            loc = n.location
            if loc.valid() and in_box(loc.lat, loc.lon):
                out["pois"].append(
                    {
                        "id": f"n{n.id}",
                        "tags": _subset(n.tags, POI_TAGS),
                        "lat": round(loc.lat, 6),
                        "lng": round(loc.lon, 6),
                        "ts": _ts(n),
                    }
                )

        def way(self, w: Any) -> None:
            tags = w.tags
            is_road = "highway" in tags
            is_building = "building" in tags
            is_poi = any(k in tags for k in POI_KEYS)
            if not (is_road or is_building or is_poi):
                return
            coords = [[round(nd.lat, 6), round(nd.lon, 6)] for nd in w.nodes if nd.location.valid()]
            if not coords or not _overlaps(_bbox(coords), box):
                return
            mid = [
                round(sum(c[0] for c in coords) / len(coords), 6),
                round(sum(c[1] for c in coords) / len(coords), 6),
            ]
            if is_road:
                out["roads"].append(
                    {
                        "id": f"w{w.id}",
                        "tags": _subset(tags, ROAD_TAGS),
                        "coords": coords,
                        "ts": _ts(w),
                    }
                )
            if is_building:
                out["buildings"].append(mid)
            if is_poi:
                out["pois"].append(
                    {
                        "id": f"w{w.id}",
                        "tags": _subset(tags, POI_TAGS),
                        "lat": mid[0],
                        "lng": mid[1],
                        "ts": _ts(w),
                    }
                )

        def area(self, a: Any) -> None:
            if not any(k in a.tags for k in AREA_KEYS):
                return
            rings = []
            for outer in a.outer_rings():
                ring = [[round(nd.lat, 6), round(nd.lon, 6)] for nd in outer]
                holes = [
                    [[round(nd.lat, 6), round(nd.lon, 6)] for nd in inner]
                    for inner in a.inner_rings(outer)
                ]
                rings.append({"outer": ring, "inner": holes})
            if not rings:
                return
            bbox = _bbox([c for r in rings for c in r["outer"]])
            if not _overlaps(bbox, box):
                return
            kind = "w" if a.from_way() else "r"
            out["areas"].append(
                {
                    "id": f"{kind}{a.orig_id()}",
                    "tags": _subset(a.tags, AREA_TAGS),
                    "bbox": bbox,
                    "rings": rings,
                    "ts": _ts(a),
                }
            )

    Handler().apply_file(str(source), locations=True)
    header = osmium.io.Reader(str(source), osmium.osm.osm_entity_bits.NOTHING)
    data_ts = header.header().get("osmosis_replication_timestamp") or ""
    header.close()
    return {
        "meta": {
            "source_file": source.name,
            "source_md5": md5_of(source),
            "osm_data_timestamp": data_ts,
            "built_at": datetime.now(UTC).isoformat(),
            "box": box,
            "counts": {k: len(v) for k, v in out.items()},
        },
        **out,
    }


def write_cache(cache: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))


# Used by osm.py to read the cache once per process.
_LOADED: dict[str, dict[str, Any]] = {}


def load_cache(path: Path) -> dict[str, Any]:
    key = str(path)
    if key not in _LOADED:
        if not path.exists():
            raise FileNotFoundError(
                f"No OSM cache at {path}; run python -m experiments.tools.geo.osm_data first"
            )
        with gzip.open(path, "rt", encoding="utf-8") as f:
            _LOADED[key] = json.load(f)
    return _LOADED[key]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local OSM cache for osm v3")
    parser.add_argument("--cases", default="v3")
    parser.add_argument("--source", default=None, help="path to egypt-latest.osm.pbf")
    parser.add_argument(
        "--delete-source", action="store_true", help="delete the .osm.pbf after the cache is built"
    )
    args = parser.parse_args()

    cases = load_cases("osm", args.cases)
    source = find_source(args.source)
    if source is None:
        print(f"No .osm.pbf given or in {DATA_DIR}; downloading {EGYPT_URL}")
        source = download()
    print(f"Reading {source} ({source.stat().st_size / 1e6:.0f} MB); this takes a few minutes")
    cache = build_cache(source, cases["box"])
    path = cache_path(args.cases)
    write_cache(cache, path)
    meta = cache["meta"]
    print(f"Cache {path} ({path.stat().st_size / 1e6:.1f} MB): {meta['counts']}")
    print(f"OSM data date: {meta['osm_data_timestamp'] or 'not in file header'}")
    if args.delete_source:
        source.unlink()
        print(f"Deleted {source}")


if __name__ == "__main__":
    main()
