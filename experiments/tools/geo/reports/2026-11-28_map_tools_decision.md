# A3 map tools: decision

Date: 2026-11-28 · Plan task: A3 (Shared research tools), tool choice · PR #27
**Decision: Google for Places, Routes and Elevation; OpenStreetMap from a local copy for roads; Serper for social.**

## Question

For each data source the Phase 1 agents need around a site (businesses, roads and land use, drive
times, terrain, social posts), which tool gives **correct, dated** data **reliably**, at the lowest cost?

## Method

- Same method as the web search decision: each tool called **directly, no LLM**, every raw response
  saved in `runs/`, measured afterwards by `score.py`. Per-tool reports are in this folder.
- **Site 1:** Ali's Manara / M Hub site in New Obour (pin from his brief). **Site 2:** El Obour City
  centre, a built-up control site, added because site 1 is almost empty within 3 km.
- Results checked against what we know: Ali's facts (plot ~28 feddans, ~220 m road frontage, new
  city), the satellite view, and the OpenStreetMap website.
- About 290 calls in total: 98 Google, 36 Foursquare, 30 Serper, the rest free services.

## Results

| Need | Compared | Reliability | What decided it | Choice |
|---|---|---|---|---|
| Businesses around the site | Google Places (New) vs Foursquare | Both 0 errors on the last runs | Google: up to 20 per search, 20–85 % rated, hours, reviews. Foursquare: 0–22, no ratings or hours on the free tier, data 2–7 years old | **Google Places** |
| Roads, land use, buildings | Public Overpass (v1, v2) vs local Geofabrik copy (v3) | Overpass 7 / 80 answered, ~30 s each; local 16 / 16, under 2 s, same numbers | Only OSM has this data. Nearest major road was right on both sites (Regional Ring Road, 154 m from Ali's pin) | **OSM, local copy** |
| Drive times | Google Routes vs OpenRouteService vs OSRM | 70 / 70 (after OpenRouteService's address fix) | Only Google has traffic: 8–27 % spread by time of day. Free tools are 3–36 % faster on paper and often take another road | **Google Routes** |
| Terrain | Google vs OpenTopoData SRTM / ASTER | 3 / 3 | Google and SRTM agree within 2.4 m; ASTER shows false steep slopes | **Google Elevation** (spec Q6 confirmed) |
| Social posts | Serper, one combined filter vs one call per platform | 29 / 30 | One call per platform finds 3–4× more; Arabic names New Obour, English drifts elsewhere | **Serper, Arabic, per platform** |

## What we learned

1. **Free public servers are the weak point, not the data.** Overpass failed almost every call and
   OpenRouteService moved its address without our code knowing. Anything the agent depends on must
   either be paid with a support promise (Google) or kept locally (OSM).
2. **"No results" can be true.** Ali's site really has 4 businesses within 3 km. The agent must
   report that honestly and escalate for planned supply, not search wider until something appears.
3. **"No results" can also be a data gap.** OSM has no buildings in Obour and misses the farms
   around Ali's site. The agent must say "not mapped", never "empty land".
4. **Limits hide coverage.** Google Nearby returns at most 20 places: at 3 km it returned the same
   20 as at 1 km. The tool must split the area or paginate, and log when it hit the cap.
5. **Arabic matters again** (as in web search): social results about New Obour come from Arabic
   queries, and Google Places names are mostly Arabic.

## Decision for A3 (shared tools module)

| Tool function | Provider and settings |
|---|---|
| `places_nearby` | Google Places (New). Split the radius into smaller circles or use Text Search with pagination; record "capped" in the search log; check `primaryType` |
| `place_details` | Google Places (New): rating, review count, hours, up to 5 reviews with dates |
| `osm_around` | Local OSM cache from Geofabrik's Egypt extract (`osm_data.py`), refreshed on a schedule; data date as evidence. Roads and access only; buildings and new-city land use flagged as "not mapped" |
| `travel_time` | Google Routes, traffic-aware, at fixed departure times (Sunday morning and evening peak, Friday midday); report the range |
| `elevation` | Google Elevation, grid over the plot; SRTM via OpenTopoData as fallback |
| `social_search` | Serper, Arabic queries, one call per platform; resolve redirect links; posts are leads, not facts |

**Cost:** Google is the only paid provider; this whole experiment used 98 Google calls. Foursquare
and OpenRouteService are not needed.

## Limits to keep in mind

- Two sites, both in the Obour area; older Cairo districts and the coast (e.g. Ain Sokhna) were not tested.
- Correctness was checked on a few facts per site, not business by business.
- Google results change over time and were collected once per site.
