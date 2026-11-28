"""Build or refresh the local OpenStreetMap cache that `osm_around` reads.

    curl -L -o data/osm/egypt-latest.osm.pbf https://download.geofabrik.de/africa/egypt-latest.osm.pbf
    python scripts/build_osm_cache.py --source data/osm/egypt-latest.osm.pbf --delete-source

Covers the areas in `app.shared.tools.osm.BOXES`; add a box and rerun to cover a new area.
"""

import argparse
import gzip
import json
from pathlib import Path

from app.shared.settings import settings
from app.shared.tools.osm import build_cache


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local OSM cache")
    parser.add_argument("--source", required=True, help="path to egypt-latest.osm.pbf")
    parser.add_argument("--delete-source", action="store_true")
    args = parser.parse_args()
    source = Path(args.source).expanduser()
    print(f"Reading {source} ({source.stat().st_size / 1e6:.0f} MB), a few minutes...")
    cache = build_cache(source)
    path = settings.osm_cache_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    print(
        f"Wrote {path} ({path.stat().st_size / 1e6:.1f} MB): {cache['meta']['counts']}, "
        f"data date {cache['meta']['data_date'] or 'unknown'}"
    )
    if args.delete_source:
        source.unlink()
        print(f"Deleted {source}")


if __name__ == "__main__":
    main()
