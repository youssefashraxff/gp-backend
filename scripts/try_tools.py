"""Call every research tool once, for real, on Ali's Manara site (New Obour), and print what
came back. Manual check for plan A3; uses the keys in .env and costs a few Google calls.

    python scripts/try_tools.py
"""

import asyncio
from datetime import UTC, datetime, timedelta

from app.shared.tools import (
    ToolRun,
    elevation,
    osm_around,
    place_details,
    places_nearby,
    travel_time,
    web_search,
)

SITE = (30.32376, 31.5566816)  # experiments/test_sites/site_01.json
OBOUR_CITY = (30.1938258, 31.4601618)


async def main() -> None:
    run = ToolRun()
    nearby = await run.call(
        places_nearby,
        lat=SITE[0],
        lng=SITE[1],
        radius_m=3000,
        types=["cafe", "coffee_shop", "supermarket"],
    )
    first = nearby.data[0]["place_id"] if nearby.data else None
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).replace(hour=15, minute=30)
    results = [
        nearby,
        await run.call(place_details, place_id=first) if first else None,
        await run.call(travel_time, origin=OBOUR_CITY, destination=SITE, depart_at=tomorrow),
        await run.call(elevation, points=[SITE]),
        await run.call(web_search, text="العبور الجديدة", lang="ar"),
        await run.call(osm_around, lat=SITE[0], lng=SITE[1]),
    ]
    for r in results:
        if r is None:
            print("place_details  skipped: no place nearby to look up")
            continue
        n = len(r.data) if isinstance(r.data, list) else ""
        print(f"{r.tool:<14} {r.status:<6} {n!s:<4} {'capped ' if r.capped else ''}{r.error}")
    osm = results[-1]
    if osm and osm.data:
        print("nearest major road:", osm.data["nearest_major_road"])


if __name__ == "__main__":
    asyncio.run(main())
