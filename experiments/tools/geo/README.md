# Map tool comparison (Places, OSM, Routes, Elevation, Social)

Same method as [`../web_search/`](../web_search/README.md): the tools are called **directly,
with no LLM**, on a fixed test site, every raw response is saved, and the saved files are
measured afterwards. The results decide which tool each agent uses (plan A3).

| Tool | Compared | Used by |
|---|---|---|
| `places` | Google Places API (New) Nearby + Details vs Foursquare Places | Competitors, Segments |
| `osm` | OpenStreetMap: public Overpass servers (v1, v2) vs a local copy of Geofabrik's Egypt extract (v3) | Site analysis |
| `routes` | Google Routes (with traffic, 5 departure times) vs OpenRouteService vs OSRM | Site analysis |
| `elevation` | Google Elevation vs OpenTopoData SRTM 30 m and ASTER 30 m | Site analysis |
| `social` | Serper with `site:` filters for Facebook, Instagram, X, TikTok | Segments (Could) |

Test sites:

- `site_01`: Ali's Manara / M Hub site in New Obour (pin from his brief, plot ~28 feddans,
  ~220 m frontage). Desert next to the Regional Ring Road, almost nothing built within 3 km.
- `site_02`: El Obour City centre, a **control** site that is not one of Ali's concepts. It
  is built up, so Places and OSM have something to find and the providers can be told apart.

## Run

Keys in `.env` (never commit it): `GOOGLE_MAPS_API_KEY` (Places API (New), Routes API and
Maps Elevation API enabled), `FOURSQUARE_API_KEY`, `OPENROUTESERVICE_API_KEY`,
`SERPER_API_KEY`. Overpass, OpenTopoData and OSRM need no key.

```bash
# see the calls without making them
python -m experiments.tools.geo.collect --tool all --site site_01 --dry-run
# call everything (about 150 calls, ~5 minutes because of the pauses)
python -m experiments.tools.geo.collect --tool all --site site_01 --notes "v1 baseline"
# or one tool
python -m experiments.tools.geo.collect --tool places --site site_01
# measure (no API calls)
python -m experiments.tools.geo.score
```

A tool whose key is missing is skipped; the others still run.

`--only <provider>[,<provider>]` runs just those providers. Follow-up calls are then built from
the runs already saved, so one failed provider can be rerun alone:

```bash
python -m experiments.tools.geo.collect --tool routes --site site_01 --only openrouteservice
```

Public OSM services (Overpass, OSRM, OpenTopoData) get a descriptive `User-Agent` and
`Referer` (`common.POLITE_HEADERS`): since 2026 `overpass-api.de` answers a generic client
with `406` and then refuses its IP for a while.

| Step | Writes |
|---|---|
| `collect.py` | one new file per call in `runs/<tool>/<cases version>/<site>/` (time first in the name, never overwritten) |
| `score.py` | `scores_<tool>.csv` (one row per run file) and `summary_<tool>.csv` (providers side by side, newest file per provider and case) |

Each run file holds the call's `params`, `status` (`ok`, `empty`, `error`), `n_items`,
`seconds`, `error` and the full `raw` response. Keys never go into run files: they are sent
in headers, and the one API that takes the key in the URL (Google Elevation) has its error
message rebuilt without the URL.

## Cases

What is asked lives in `cases/<tool>_<version>.json`. Never edit a version that has been
run; add `<tool>_v2.json` and run with `--cases v2`.

| File | What it asks |
|---|---|
| `places_v1` | 6 kinds from the M Hub concept (cafe, restaurant, pharmacy, grocery, sports/padel, mall) at 1 km and 3 km; then Place Details for the 5 nearest Google places with reviews |
| `osm_v1` | areas containing the pin; roads 1 km; major roads 3 km; land use 1 km; buildings 500 m and 1 km; points of interest 1 km and 3 km |
| `osm_v2` | osm_v1's queries with the descriptive headers, a third server (`overpass.private.coffee`) and 5 s between calls |
| `osm_v3` | the same questions answered from a local cache of the Egypt extract (box: east Greater Cairo to 10th of Ramadan), built by `osm_data.py` |

### osm v3: local OpenStreetMap

The public Overpass servers answered 7 of 48 calls in v2 (the rest: 502, 504 or no answer in
90 s). v3 reads the same OpenStreetMap data from a file instead:

```bash
# once: read the Egypt file (yours, or downloaded and checksum-checked) into a small cache
python -m experiments.tools.geo.osm_data --cases v3 --source /path/to/egypt-latest.osm.pbf --delete-source
# then the usual run, now answered locally
python -m experiments.tools.geo.collect --tool osm --site site_01 --cases v3
```

`osm_data.py` keeps only what the questions need inside the case file's `box` (roads with
their shape, land-use / boundary / place outlines, one point per building, points of
interest) in `data/osm_cache_v3.json.gz`, with the data's date from the file header.
`data/` is git-ignored. Local answers have Overpass's JSON shape, so scoring is unchanged.
Distances to roads are measured to the nearest segment, not the nearest vertex.
| `routes_v1` | 5 landmarks (airport, Obour City, Heliopolis, Madinaty, 10th of Ramadan), both directions, Sunday 08:00, 13:00, 17:30, 22:00 and Friday 13:00 (Cairo time, the next such day) |
| `elevation_v1` | 7 x 7 grid 100 m apart over the plot, plus 8 points at 1 km and 3 km |
| `social_v1` | 6 questions (4 Arabic, 2 English), once with all platforms in one `site:` filter and once per platform |

## What is measured

| Tool | Main columns |
|---|---|
| places | places found, within radius, with rating, with reviews, median reviews, with opening hours, nearest; side by side: found by both, only Google, only Foursquare, `google_capped_at_20` (Google returns at most 20 per call); details: newest and oldest review age |
| osm | elements, edit age, road classes, nearest major road (distance, class, name), land use mix, building count, POI kinds, what the pin sits inside; side by side: each server's status, count and time |
| routes | minutes per departure time, Google's no-traffic minutes, km; side by side: traffic spread (max vs min), OpenRouteService and OSRM against Google's no-traffic time |
| elevation | plot min / max / relief, max and mean slope between neighbouring points, relief of the wider ring, Google's resolution; difference from Google per provider |
| social | results, results naming the place, dated, last 12 months, per platform; side by side: how many results the per-platform calls found that the single combined call missed |

Places that both providers found are matched by distance (≤ 150 m) and shared name words.
Social results are matched by title, because most Serper links are `google.com/goto?url=<token>`
redirects whose token changes on every call.
