# Elevation: Google vs OpenTopoData (SRTM, ASTER)

Date: 2026-11-28 · Plan task: A3 · Cases: `elevation_v1` · Site: `site_01` (Ali's Manara site)

## Inputs and settings

- 65 points: a 7 × 7 grid 100 m apart over the plot (600 m × 600 m, larger than the ~117,600 m² plot), plus 8 points at 1 km and at 3 km.
- The same points, in one call each, to Google Elevation and to OpenTopoData's free SRTM 30 m and ASTER 30 m datasets.
- Slope is measured between neighbouring grid points (100 m apart).

## Results

All 3 calls answered, no missing points.

| Provider | Plot low–high (m) | Relief over the plot | Max slope | Mean slope | Relief within 3 km | Mean difference from Google |
|---|---|---|---|---|---|---|
| **Google** (resolution ~9.5 m) | 85.5–97.9 | 12.4 m | 4.5 % | 1.5 % | 116.7 m | n/a |
| OpenTopoData SRTM 30 m | 84–101 | 17 m | 6.0 % | 2.2 % | 117 m | 2.4 m |
| OpenTopoData ASTER 30 m | 77–105 | 28 m | 22 % | 6.0 % | 116 m | 4.8 m |

- **Google and SRTM agree** (2.4 m apart on average) and both say the plot is **gently sloping**: about 12–17 m from one corner to the other, 1.5–2 % on average.
- **ASTER is noisy**: it shows 22 % slopes the other two do not. It should not be used for slopes.
- The terrain around rises and falls about 117 m within 3 km, so the wider area is not flat even though the plot is.

## What it means

1. **Google Elevation is confirmed** (it was already the spec's choice, Q6): finest resolution, no failures, 1 call per site.
2. **SRTM 30 m via OpenTopoData is a usable free fallback** for flat-or-sloping judgements, not for exact heights.
3. **Ali's "new city, buildable land" fits:** about 1.5 % average slope over the plot needs normal levelling, not major earthworks. The exact levels still need a survey (his notes list levels as an open item).

## Weak spots of this test

- One site. Steep sites (e.g. NAWA's cliff in Ain Sokhna) would test the providers harder.
- 100 m spacing averages out small features (ditches, mounds).
