"""Measure every saved run file. Calls no API, so rescoring is free.

Run:
    python -m experiments.tools.geo.score

Writes, for each tool that has runs:
    scores_<tool>.csv   one row per run file
    summary_<tool>.csv  the providers side by side (latest file per provider and case)
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from experiments.tools.geo import elevation, osm, places, routes, social
from experiments.tools.geo.common import BASE_DIR, load_cases

COMMON = [
    "run_file",
    "timestamp",
    "site_id",
    "case_version",
    "tool",
    "provider",
    "case",
    "status",
    "n_items",
    "seconds",
    "error",
]


def load_runs(tool: str, base_dir: Path = BASE_DIR) -> list[tuple[str, dict[str, Any]]]:
    folder = base_dir / "runs" / tool
    if not folder.exists():
        return []
    files = sorted(folder.rglob("*.json"))
    return [(f.name, json.loads(f.read_text(encoding="utf-8"))) for f in files]


def latest(runs: list[tuple[str, dict[str, Any]]]) -> dict[tuple, dict[str, Any]]:
    """The newest file per (site, cases version, provider, case). Names start with the time."""
    out: dict[tuple, dict[str, Any]] = {}
    for _name, p in sorted(runs, key=lambda r: r[0]):
        out[(p["site_id"], p["case_version"], p["provider"], p["case"])] = p
    return out


def score_row(tool: str, name: str, p: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    row = {k: p.get(k, "") for k in COMMON if k != "run_file"}
    row["run_file"] = name
    row["error"] = (p.get("error") or "")[:200]
    if p.get("status") == "error":
        return row
    if tool == "places":
        row.update(places.score_file(p))
    elif tool == "osm":
        row.update(osm.score_file(p))
    elif tool == "routes":
        row.update(routes.score_file(p))
    elif tool == "elevation":
        row.update(elevation.score_file(p))
    elif tool == "social":
        cases = load_cases("social", p["case_version"], base_dir)
        scored = social.score_file(p, cases["platforms"], cases["place_words"])
        scored.pop("urls")
        scored.pop("titles")
        row.update(scored)
    return row


# ---------------------------------------------------------------------------------------
# Side-by-side summaries
# ---------------------------------------------------------------------------------------


def summary_places(newest: dict[tuple, dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, dict[str, dict[str, Any]]] = defaultdict(dict)
    for (site, ver, prov, case), p in newest.items():
        if not case.startswith("details_"):
            groups[(site, ver, case)][prov] = p
    rows = []
    for (site, ver, case), provs in sorted(groups.items()):
        g, f = provs.get("google"), provs.get("foursquare")
        gi = places.items(g) if g and g["status"] != "error" else []
        fi = places.items(f) if f and f["status"] != "error" else []
        row = {
            "site_id": site,
            "case_version": ver,
            "case": case,
            "google_status": g["status"] if g else "",
            "foursquare_status": f["status"] if f else "",
            "google_n": len(gi),
            "foursquare_n": len(fi),
            "google_with_reviews": sum(1 for i in gi if i["n_reviews"]),
            "foursquare_with_reviews": sum(1 for i in fi if i["n_reviews"]),
            "google_capped_at_20": len(gi) >= 20,
        }
        row.update(places.overlap(gi, fi))
        rows.append(row)
    return rows


def summary_osm(newest: dict[tuple, dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, dict[str, dict[str, Any]]] = defaultdict(dict)
    for (site, ver, prov, case), p in newest.items():
        groups[(site, ver, case)][prov] = p
    rows = []
    for (site, ver, case), provs in sorted(groups.items()):
        row: dict[str, Any] = {"site_id": site, "case_version": ver, "case": case}
        for prov, p in sorted(provs.items()):
            row[f"{prov}_status"] = p["status"]
            row[f"{prov}_n"] = p["n_items"]
            row[f"{prov}_seconds"] = p["seconds"]
        rows.append(row)
    return rows


def summary_routes(newest: dict[tuple, dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for (site, ver, _prov, _case), p in newest.items():
        if p["status"] == "error":
            continue
        s = routes.score_file(p)
        groups[(site, ver, s["landmark"], s["direction"])].append({**s, "provider": p["provider"]})
    rows = []
    for (site, ver, lm, direction), items in sorted(groups.items()):
        google = [i for i in items if i["provider"] == "google" and i["minutes"] is not None]
        mins = [i["minutes"] for i in google]
        static = [i["no_traffic_minutes"] for i in google if i["no_traffic_minutes"]]
        by_slot = {i["slot"]: i["minutes"] for i in google}
        other = {i["provider"]: i for i in items if i["provider"] != "google"}
        row: dict[str, Any] = {
            "site_id": site,
            "case_version": ver,
            "landmark": lm,
            "direction": direction,
            "google_min_minutes": min(mins) if mins else None,
            "google_max_minutes": max(mins) if mins else None,
            "traffic_spread_pct": round((max(mins) - min(mins)) / min(mins) * 100)
            if mins and min(mins)
            else None,
            "google_no_traffic_minutes": round(sum(static) / len(static), 1) if static else None,
            "google_km": google[0]["km"] if google else None,
        }
        for slot, m in sorted(by_slot.items()):
            row[f"google_{slot}"] = m
        for prov in ("openrouteservice", "osrm"):
            row[f"{prov}_minutes"] = other[prov]["minutes"] if prov in other else None
            row[f"{prov}_km"] = other[prov]["km"] if prov in other else None
        rows.append(row)
    return rows


def summary_elevation(newest: dict[tuple, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    google = {(k[0], k[1]): p for k, p in newest.items() if k[2] == "google"}
    for (site, ver, prov, _case), p in sorted(newest.items()):
        if p["status"] == "error":
            rows.append({"site_id": site, "case_version": ver, "provider": prov, "status": "error"})
            continue
        row = {"site_id": site, "case_version": ver, "provider": prov, "status": p["status"]}
        row.update(elevation.score_file(p))
        g = google.get((site, ver))
        if g and prov != "google" and g["status"] != "error":
            row["mean_abs_diff_vs_google_m"] = elevation.mean_abs_diff(
                elevation.heights(p), elevation.heights(g)
            )
        rows.append(row)
    return rows


def summary_social(newest: dict[tuple, dict[str, Any]], base_dir: Path) -> list[dict[str, Any]]:
    groups: dict[tuple, dict[str, dict[str, Any]]] = defaultdict(dict)
    for (site, ver, _prov, _case), p in newest.items():
        groups[(site, ver, p["meta"]["query_id"])][p["meta"]["variant"]] = p
    rows = []
    for (site, ver, qid), variants in sorted(groups.items()):
        cases = load_cases("social", ver, base_dir)
        plat, words = cases["platforms"], cases["place_words"]
        all_v = variants.get("all")
        all_s = (
            social.score_file(all_v, plat, words) if all_v and all_v["status"] != "error" else None
        )
        all_titles = set(all_s["titles"]) if all_s else set()
        per = {
            name: social.score_file(p, plat, words)
            for name, p in variants.items()
            if name != "all" and p["status"] != "error"
        }
        union = set().union(*(set(s["titles"]) for s in per.values())) if per else set()
        row: dict[str, Any] = {
            "site_id": site,
            "case_version": ver,
            "query_id": qid,
            "all_n": len(all_titles),
            "all_mentions_place": all_s["n_mentions_place"] if all_s else 0,
            "per_platform_union_n": len(union),
            "missed_by_all_call": len(union - all_titles),
        }
        for name, s in sorted(per.items()):
            row[f"{name}_n"] = s["n_results"]
            row[f"{name}_mentions_place"] = s["n_mentions_place"]
            row[f"{name}_last_12_months"] = s["n_last_12_months"]
        rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def score_tool(tool: str, base_dir: Path = BASE_DIR) -> tuple[int, int]:
    runs = load_runs(tool, base_dir)
    if not runs:
        return 0, 0
    rows = [score_row(tool, name, p, base_dir) for name, p in runs]
    write_csv(base_dir / f"scores_{tool}.csv", rows)
    newest = latest(runs)
    summary = {
        "places": lambda: summary_places(newest),
        "osm": lambda: summary_osm(newest),
        "routes": lambda: summary_routes(newest),
        "elevation": lambda: summary_elevation(newest),
        "social": lambda: summary_social(newest, base_dir),
    }[tool]()
    write_csv(base_dir / f"summary_{tool}.csv", summary)
    return len(rows), len(summary)


def main() -> None:
    for tool in ("places", "osm", "routes", "elevation", "social"):
        n, s = score_tool(tool)
        if n:
            print(f"{tool}: {n} run files scored -> scores_{tool}.csv, summary_{tool}.csv ({s})")
        else:
            print(f"{tool}: no runs yet")


if __name__ == "__main__":
    main()
