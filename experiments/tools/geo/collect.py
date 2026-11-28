"""Call the map tools for one test site and save every raw response. No LLM, no scoring.

Run (from the repo root, with the keys in `.env`):
    python -m experiments.tools.geo.collect --tool all --site site_01 --notes "first run"
    python -m experiments.tools.geo.collect --tool places --site site_01 --dry-run

Each call becomes one new file in `runs/<tool>/<cases version>/<site>/` (never
overwritten). Then run `python -m experiments.tools.geo.score`.
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

from pydantic import SecretStr

from experiments.tools.geo import elevation, osm, places, routes, social
from experiments.tools.geo.common import (
    BASE_DIR,
    PAUSE_SECONDS,
    Call,
    Keys,
    load_cases,
    load_site,
    run_call,
    runs_dir,
    save_run,
)

TOOLS: dict[str, ModuleType] = {
    "places": places,
    "osm": osm,
    "routes": routes,
    "elevation": elevation,
    "social": social,
}


def _dry_keys() -> Keys:
    fake = SecretStr("dry-run")
    return Keys(
        google_maps_api_key=fake,
        foursquare_api_key=fake,
        openrouteservice_api_key=fake,
        serper_api_key=fake,
    )


def collect_tool(
    tool: str,
    site_id: str,
    version: str,
    notes: str,
    keys: Keys,
    dry_run: bool = False,
    base_dir=BASE_DIR,
    pause: float = PAUSE_SECONDS,
) -> list[dict[str, Any]]:
    """Run one tool's calls (then its follow-up calls) and save each result."""
    module = TOOLS[tool]
    site = load_site(site_id)
    cases = load_cases(tool, version, base_dir)
    folder = runs_dir(tool, version, site_id, base_dir)
    calls: list[Call] = module.build_calls(site, cases, keys)
    if dry_run:
        print(f"[{tool}] {len(calls)} calls planned (+ follow-ups after them):")
        for c in calls:
            print(f"  {c.provider:<22} {c.case}")
        return []

    results: list[dict[str, Any]] = []

    def run(batch: list[Call]) -> None:
        for call in batch:
            res = run_call(call)
            res.update(
                {
                    "site_id": site_id,
                    "case_version": version,
                    "notes": notes,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            save_run(folder, res)
            results.append(res)
            err = f"  {res['error'][:120]}" if res["error"] else ""
            print(
                f"[{tool}] {res['provider']:<22} {res['case']:<32} {res['status']:<6}"
                f" items={res['n_items']:<4} {res['seconds']}s{err}"
            )
            time.sleep(pause)

    run(calls)
    run(module.followup_calls(results, cases, keys))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--tool", default="all", choices=[*TOOLS, "all"])
    parser.add_argument("--site", default="site_01")
    parser.add_argument("--cases", default="v1", help="case file version, e.g. v1")
    parser.add_argument("--notes", default="")
    parser.add_argument("--dry-run", action="store_true", help="list the calls, call nothing")
    args = parser.parse_args()

    keys = _dry_keys() if args.dry_run else Keys()
    tools = list(TOOLS) if args.tool == "all" else [args.tool]
    for tool in tools:
        try:
            results = collect_tool(tool, args.site, args.cases, args.notes, keys, args.dry_run)
        except RuntimeError as exc:  # a missing key stops this tool only
            print(f"[{tool}] skipped: {exc}")
            continue
        if results:
            ok = sum(1 for r in results if r["status"] == "ok")
            print(f"[{tool}] done: {ok}/{len(results)} ok")


if __name__ == "__main__":
    main()
