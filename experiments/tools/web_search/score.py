"""Score the saved web search runs. Reads only files, never calls a tool.

Inputs:  runs/*.json, egypt_sources.csv, international_sources.csv
Outputs: scores.csv   one row per run file           (regenerated every time)
         summary.csv  one row per tool+settings+query (regenerated every time)
         manual.csv   `relevant` and `notes`, filled by hand, keyed by run file name.
                      Rows are only ever added, so rescoring never deletes what you wrote.

Run:  python -m experiments.tools.web_search.score
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
SOURCE_FILES = ("egypt_sources.csv", "international_sources.csv")

IGNORE = "ignore"  # e.g. tavily.com: dropped from every count
UNLISTED_EG = "unlisted_eg"  # not in either list, but the domain ends in .eg

# scores.csv column -> the source_type values it counts
TYPE_GROUPS: dict[str, set[str]] = {
    "n_official": {"official", "intl_official"},
    "n_news": {"news", "business_news", "intl_news"},
    "n_report": {"consultancy_report", "data_aggregator"},
    "n_listing": {"listing_portal", "travel_booking", "str_data"},
    "n_developer": {"developer_broker"},
    "n_social": {"social"},
    "n_paid_report": {"paid_report"},
}
COUNT_COLUMNS = [
    "n_results",
    "n_egyptian",
    *TYPE_GROUPS,
    "n_unlisted",
    "n_with_date",
]
SCORES_COLUMNS = [
    "run_file",
    "timestamp",
    "tool",
    "settings",
    "query_version",
    "query_id",
    "site",
    "group",
    "run",
    "status",
    *COUNT_COLUMNS,
    "unlisted_domains",
    "top3_urls",
    "seconds",
    "error",
]
SUMMARY_COLUMNS = [
    "tool",
    "settings",
    "query_version",
    "query_id",
    "site",
    "group",
    "runs",
    "ok",
    "empty",
    "errors",
    *(f"avg_{c}" for c in COUNT_COLUMNS),
    "same_top3",
    "avg_seconds",
]
MANUAL_COLUMNS = ["run_file", "tool", "settings", "query_id", "run", "relevant", "notes"]


# ---------------------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    source_type: str
    egyptian: bool


def load_sources(base_dir: Path = BASE_DIR) -> dict[str, Source]:
    """domain -> Source, from both source CSVs."""
    sources: dict[str, Source] = {}
    for name in SOURCE_FILES:
        with (base_dir / name).open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                domain = normalize_domain(row["domain"])
                if domain:
                    sources[domain] = Source(
                        source_type=row["source_type"].strip(),
                        egyptian=row.get("egyptian", "").strip().lower() == "yes",
                    )
    return sources


def normalize_domain(text: str) -> str:
    """Lowercase, strip `www.`. Accepts a bare domain or a full URL."""
    text = text.strip().lower()
    host = urlparse(text).hostname if "://" in text else text
    return (host or "").removeprefix("www.")


def classify(url: str, sources: dict[str, Source]) -> tuple[str, Source | None]:
    """(domain, matching Source or None). Suffix match, so `english.ahram.org.eg` matches
    `ahram.org.eg`; the longest listed suffix wins. An unlisted `.eg` domain is Egyptian
    with type `unlisted_eg`."""
    domain = normalize_domain(url)
    parts = domain.split(".")
    for i in range(len(parts)):  # longest suffix first
        source = sources.get(".".join(parts[i:]))
        if source is not None:
            return domain, source
    if domain.endswith(".eg"):
        return domain, Source(UNLISTED_EG, egyptian=True)
    return domain, None


# ---------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------


def _status(run: dict[str, Any]) -> str:
    # Older run files (before the retry was added) don't store a status.
    if run.get("status"):
        return run["status"]
    if run.get("error"):
        return "error"
    return "ok" if run.get("normalized") else "empty"


def score_run(run_file: str, run: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    counts = dict.fromkeys(COUNT_COLUMNS, 0)
    unlisted: set[str] = set()
    kept: list[dict[str, Any]] = []
    for result in run.get("normalized") or []:
        domain, source = classify(result.get("url", ""), sources)
        if source is not None and source.source_type == IGNORE:
            continue
        kept.append(result)
        counts["n_results"] += 1
        counts["n_with_date"] += bool(result.get("published_date"))
        if source is not None and source.egyptian:
            counts["n_egyptian"] += 1
        if source is None or source.source_type == UNLISTED_EG:
            counts["n_unlisted"] += 1
            unlisted.add(domain)
            continue
        for column, types in TYPE_GROUPS.items():
            if source.source_type in types:
                counts[column] += 1

    q = run["query"]
    return {
        "run_file": run_file,
        "timestamp": run["timestamp"],
        "tool": run["tool"],
        "settings": run["settings_version"],
        "query_version": run["query_version"],
        "query_id": q["id"],
        "site": q["site"],
        "group": q["group"],
        "run": run["run"],
        "status": _status(run),
        **counts,
        "unlisted_domains": "; ".join(sorted(unlisted)),
        "top3_urls": " | ".join(r.get("url", "") for r in kept[:3]),
        "seconds": run.get("seconds", ""),
        "error": run.get("error") or "",
    }


def summarize(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per tool + settings + query. Averages are over runs that didn't error
    (an empty answer is a real answer); same_top3 is over `ok` runs: how many of them share
    the most common top-3 set (order ignored)."""
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for s in scores:
        key = (s["tool"], s["settings"], s["query_version"], s["query_id"])
        groups.setdefault(key, []).append(s)

    rows = []
    for (tool, settings, query_version, query_id), runs in groups.items():
        answered = [r for r in runs if r["status"] != "error"]
        ok = [r for r in runs if r["status"] == "ok"]
        top3 = Counter(frozenset(r["top3_urls"].split(" | ")) for r in ok)
        row: dict[str, Any] = {
            "tool": tool,
            "settings": settings,
            "query_version": query_version,
            "query_id": query_id,
            "site": runs[0]["site"],
            "group": runs[0]["group"],
            "runs": len(runs),
            "ok": len(ok),
            "empty": sum(r["status"] == "empty" for r in runs),
            "errors": len(runs) - len(answered),
        }
        for c in COUNT_COLUMNS:
            row[f"avg_{c}"] = _avg([r[c] for r in answered])
        row["same_top3"] = top3.most_common(1)[0][1] if top3 else 0
        row["avg_seconds"] = _avg([float(r["seconds"]) for r in answered if r["seconds"] != ""])
        rows.append(row)
    return rows


def _avg(values: list[float]) -> float | str:
    return round(sum(values) / len(values), 2) if values else ""


def totals(scores: list[dict[str, Any]]) -> dict[str, float]:
    """Share of all counted results per column (n_results excluded), for a quick overview."""
    total = sum(s["n_results"] for s in scores)
    if not total:
        return {}
    return {c: sum(s[c] for s in scores) / total for c in COUNT_COLUMNS if c != "n_results"}


# ---------------------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------------------


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sync_manual(path: Path, scores: list[dict[str, Any]], runs: dict[str, dict]) -> int:
    """Add a row for every run file that manual.csv doesn't have yet. Existing rows (and
    rows whose run file is gone) are kept exactly as they are. Returns how many were added."""
    existing: list[dict[str, str]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            existing = list(csv.DictReader(f))
    known = {r["run_file"] for r in existing}
    added = [
        {
            "run_file": s["run_file"],
            "tool": s["tool"],
            "settings": s["settings"],
            "query_id": s["query_id"],
            "run": s["run"],
            "relevant": "",
            "notes": runs[s["run_file"]].get("notes", ""),
        }
        for s in scores
        if s["run_file"] not in known
    ]
    if added or not path.exists():
        _write_csv(path, MANUAL_COLUMNS, existing + added)
    return len(added)


def score_all(base_dir: Path = BASE_DIR) -> list[dict[str, Any]]:
    sources = load_sources(base_dir)
    runs = {
        p.name: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((base_dir / "runs").glob("*.json"))
    }
    scores = [score_run(name, run, sources) for name, run in runs.items()]
    _write_csv(base_dir / "scores.csv", SCORES_COLUMNS, scores)
    _write_csv(base_dir / "summary.csv", SUMMARY_COLUMNS, summarize(scores))
    added = sync_manual(base_dir / "manual.csv", scores, runs)
    print(f"Scored {len(scores)} run files -> scores.csv, summary.csv")
    print(f"manual.csv: {added} new rows (existing rows untouched)")
    return scores


def main() -> None:
    scores = score_all()
    shares = totals(scores)
    if shares:
        print("\nShare of all counted results:")
        for column, share in shares.items():
            print(f"  {column:15} {share:6.1%}")


if __name__ == "__main__":
    main()
