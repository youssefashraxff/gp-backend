"""Research tools shared by the Phase 1 agents (plan A3; choices in experiments/tools/*/reports).

Every tool is an async function returning a `ToolResult`; none raises. Agents call them
through one `ToolRun` per phase run, which caches identical calls and logs every search:

    run = ToolRun()
    res = await run.call(places_nearby, lat=30.19, lng=31.46, radius_m=1000, types=["cafe"])
    if res.status != "ok": ...  # escalate (spec 5.6)
"""

from app.shared.tools.base import ToolResult, ToolRun
from app.shared.tools.elevation import elevation
from app.shared.tools.osm import osm_around
from app.shared.tools.places import place_details, places_nearby
from app.shared.tools.routes import travel_time
from app.shared.tools.web_search import SOCIAL_SITES, web_search

__all__ = [
    "SOCIAL_SITES",
    "ToolResult",
    "ToolRun",
    "elevation",
    "osm_around",
    "place_details",
    "places_nearby",
    "travel_time",
    "web_search",
]
