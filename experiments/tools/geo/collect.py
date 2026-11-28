"""Call the map tools for one test site and save every raw response. No LLM, no scoring.

Run (from the repo root, with the keys in `.env`):
    python -m experiments.tools.geo.collect --tool all --site site_01 --notes "first run"
    python -m experiments.tools.geo.collect --tool places --site site_01 --dry-run

Each call becomes one new file in `runs/<tool>/<cases version>/<site>/` (never
overwritten). Then run `python -m experiments.tools.geo.score`.
"""

from __future__ import annotations

import argparse
import json
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


def load_saved(folder) -> list[dict[str, Any]]:
    """Every run file already saved in a folder, oldest first (names start with the time)."""
    if not folder.exists():
        return []
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(folder.glob("*.json"))]


def collect_tool(
    tool: str,
    site_id: str,
    version: str,
    notes: str,
    keys: Keys,
    dry_run: bool = False,
    base_dir=BASE_DIR,
    pause: float | None = None,
    only: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run one tool's calls (then its follow-up calls) and save each result.

    `only` keeps just those providers. Follow-up calls are then built from every saved
    run in the folder, so e.g. OpenRouteService can be rerun alone on the landmark points
    an earlier Google run resolved, without calling Google again.
    """
    module = TOOLS[tool]
    site = load_site(site_id)
    cases = load_cases(tool, version, base_dir)
    folder = runs_dir(tool, version, site_id, base_dir)
    wait = float(cases.get("pause_seconds", PAUSE_SECONDS)) if pause is None else pause
    calls: list[Call] = module.build_calls(site, cases, keys)
    if only:
        calls = [c for c in calls if c.provider in only]
    if dry_run:
        if only:  # follow-ups from what is already saved
            later = module.followup_calls(load_saved(folder), cases, keys)
            calls += [c for c in later if c.provider in only]
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
            time.sleep(wait)

    run(calls)
    basis = load_saved(folder) if only else results
    followups = module.followup_calls(basis, cases, keys)
    run([c for c in followups if not only or c.provider in only])
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--tool", default="all", choices=[*TOOLS, "all"])
    parser.add_argument("--site", default="site_01")
    parser.add_argument("--cases", default="v1", help="case file version, e.g. v1")
    parser.add_argument("--notes", default="")
    parser.add_argument("--dry-run", action="store_true", help="list the calls, call nothing")
    parser.add_argument(
        "--only", default="", help="comma-separated providers to run, e.g. openrouteservice"
    )
    args = parser.parse_args()

    keys = _dry_keys() if args.dry_run else Keys()
    tools = list(TOOLS) if args.tool == "all" else [args.tool]
    for tool in tools:
        try:
            only = [x.strip() for x in args.only.split(",") if x.strip()] or None
            results = collect_tool(
                tool, args.site, args.cases, args.notes, keys, args.dry_run, only=only
            )
        except RuntimeError as exc:  # a missing key stops this tool only
            print(f"[{tool}] skipped: {exc}")
            continue
        if results:
            ok = sum(1 for r in results if r["status"] == "ok")
            print(f"[{tool}] done: {ok}/{len(results)} ok")


if __name__ == "__main__":
    main()
