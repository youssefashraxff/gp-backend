"""Compare web search tools directly, with no LLM involved.

The same fixed queries (`queries.json`) go to a tool several times. Every raw response is
saved to `runs/` (one new file per call, never overwritten) and one row per call is
appended to `results.csv`, so tools and settings versions can be compared on the same
queries: how many results, how many Egyptian, how many dated, and how stable the top 3 are.

Run:
    python -m experiments.tools.web_search.compare --tool tavily --settings v1 --runs 8 \
        --query all --notes "first baseline"

Add a tool: write one `search_<tool>(query, settings)` function, register it in `TOOLS`,
and add `settings/<tool>_v1.json`.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
PAUSE_SECONDS = 0.5
TIMEOUT_SECONDS = 30

RESULTS_COLUMNS = [
    "timestamp",
    "tool",
    "settings",
    "query_version",
    "query_id",
    "site",
    "group",
    "run",
    "n_results",
    "n_egyptian",
    "n_with_date",
    "n_unique_domains",
    "top3_urls",
    "seconds",
    "error",
    "relevant",
    "notes",
]


@dataclass
class Result:
    """One search result in the same shape for every tool."""

    url: str
    title: str
    snippet: str
    published_date: str | None = None
    score: float | None = None


# A tool: takes the query text and the settings dict, returns (raw_response, results).
ToolFn = Callable[[str, dict[str, Any]], tuple[Any, list[Result]]]


class _Keys(BaseSettings):
    """API keys from the environment or `.env`. SecretStr keeps them out of prints and logs."""

    model_config = SettingsConfigDict(env_file=BASE_DIR.parents[2] / ".env", extra="ignore")

    tavily_api_key: SecretStr | None = None


def _require(key: SecretStr | None, name: str) -> str:
    if key is None or not key.get_secret_value():
        raise RuntimeError(f"{name} is not set; add it to .env")
    return key.get_secret_value()


# ---------------------------------------------------------------------------------------
# Tools: one function each.
# ---------------------------------------------------------------------------------------


def search_tavily(query: str, settings: dict[str, Any]) -> tuple[Any, list[Result]]:
    from tavily import TavilyClient  # imported here so tests and other tools don't need it

    client = TavilyClient(api_key=_require(_Keys().tavily_api_key, "TAVILY_API_KEY"))
    raw = client.search(query, timeout=TIMEOUT_SECONDS, **settings)
    results = [
        Result(
            url=r.get("url", ""),
            title=r.get("title", ""),
            snippet=r.get("content", ""),
            published_date=r.get("published_date") or None,
            score=r.get("score"),
        )
        for r in raw.get("results", [])
    ]
    return raw, results


TOOLS: dict[str, ToolFn] = {"tavily": search_tavily}


# ---------------------------------------------------------------------------------------
# Loading inputs
# ---------------------------------------------------------------------------------------


def load_queries(base_dir: Path = BASE_DIR) -> dict[str, Any]:
    return json.loads((base_dir / "queries.json").read_text(encoding="utf-8"))


def load_settings(tool: str, version: str, base_dir: Path = BASE_DIR) -> dict[str, Any]:
    path = base_dir / "settings" / f"{tool}_{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"No settings '{version}' for {tool} at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_egypt_domains(base_dir: Path = BASE_DIR) -> set[str]:
    lines = (base_dir / "egypt_domains.txt").read_text(encoding="utf-8").splitlines()
    return {line.strip().lower() for line in lines if line.strip() and not line.startswith("#")}


# ---------------------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------------------


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def is_egyptian(url: str, egypt_domains: set[str]) -> bool:
    host = domain_of(url)
    if host.endswith(".eg"):
        return True
    return any(host == d or host.endswith("." + d) for d in egypt_domains)


def measure(results: list[Result], egypt_domains: set[str]) -> dict[str, Any]:
    return {
        "n_results": len(results),
        "n_egyptian": sum(is_egyptian(r.url, egypt_domains) for r in results),
        "n_with_date": sum(bool(r.published_date) for r in results),
        "n_unique_domains": len({domain_of(r.url) for r in results}),
        "top3_urls": " | ".join(r.url for r in results[:3]),
    }


# ---------------------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------------------


def save_run(runs_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    """Write a new run file. Mode "x" refuses to overwrite an existing file."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / name
    with path.open("x", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    return path


def append_row(results_csv: Path, row: dict[str, Any]) -> None:
    new_file = not results_csv.exists() or results_csv.stat().st_size == 0
    with results_csv.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def run_once(
    tool: str,
    settings_version: str,
    settings: dict[str, Any],
    query_version: str,
    q: dict[str, str],
    run: int,
    egypt_domains: set[str],
    notes: str = "",
    base_dir: Path = BASE_DIR,
) -> dict[str, Any]:
    """Call the tool once, save the raw response, append a results row. Never raises for a
    failed call: the error goes into the row and the run file."""
    now = datetime.now(UTC)
    start = time.perf_counter()
    raw: Any = None
    results: list[Result] = []
    error = ""
    try:
        raw, results = TOOLS[tool](q["query"], dict(settings))
    except Exception as exc:  # noqa: BLE001 (any failure is a result to record, not a crash)
        error = f"{type(exc).__name__}: {exc}"
    seconds = round(time.perf_counter() - start, 3)

    # Time first, so sorting by name is sorting by time.
    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    name = f"{stamp}__{tool}__{settings_version}__{q['id']}__run{run}.json"
    save_run(
        base_dir / "runs",
        name,
        {
            "timestamp": now.isoformat(),
            "tool": tool,
            "settings_version": settings_version,
            "settings": settings,
            "query_version": query_version,
            "query": q,
            "run": run,
            "seconds": seconds,
            "error": error or None,
            "normalized": [asdict(r) for r in results],
            "raw_response": raw,
        },
    )

    row = {
        "timestamp": now.isoformat(timespec="seconds"),
        "tool": tool,
        "settings": settings_version,
        "query_version": query_version,
        "query_id": q["id"],
        "site": q["site"],
        "group": q["group"],
        "run": run,
        **measure(results, egypt_domains),
        "seconds": seconds,
        "error": error,
        "relevant": "",
        "notes": notes,
    }
    append_row(base_dir / "results.csv", row)
    return row


def summarize(rows: list[dict[str, Any]]) -> list[str]:
    """One line per query: average results, average Egyptian results, top-3 stability."""
    lines = []
    by_query: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_query.setdefault(row["query_id"], []).append(row)
    for query_id, qrows in by_query.items():
        ok = [r for r in qrows if not r["error"]]
        errors = len(qrows) - len(ok)
        if not ok:
            lines.append(f"{query_id}: all {len(qrows)} runs failed")
            continue
        avg_results = sum(r["n_results"] for r in ok) / len(ok)
        avg_egypt = sum(r["n_egyptian"] for r in ok) / len(ok)
        # Order-insensitive: the same three URLs in another order count as the same top 3.
        top3_sets = Counter(frozenset(r["top3_urls"].split(" | ")) for r in ok)
        stable = top3_sets.most_common(1)[0][1]
        lines.append(
            f"{query_id}: avg results {avg_results:.1f}, avg Egyptian {avg_egypt:.1f}, "
            f"top-3 stable {stable}/{len(ok)}" + (f", errors {errors}" if errors else "")
        )
    return lines


def compare(
    tool: str,
    settings_version: str,
    runs: int,
    query: str = "all",
    notes: str = "",
    base_dir: Path = BASE_DIR,
    pause: float = PAUSE_SECONDS,
) -> list[dict[str, Any]]:
    if tool not in TOOLS:
        raise SystemExit(f"Unknown tool '{tool}'. Known: {', '.join(TOOLS)}")
    settings = load_settings(tool, settings_version, base_dir)
    queries = load_queries(base_dir)
    selected = [q for q in queries["queries"] if query in ("all", q["id"])]
    if not selected:
        raise SystemExit(f"Unknown query '{query}'")
    egypt_domains = load_egypt_domains(base_dir)

    rows = []
    for q in selected:
        for run in range(1, runs + 1):
            row = run_once(
                tool, settings_version, settings, queries["version"], q, run,
                egypt_domains, notes, base_dir,
            )
            status = f"error: {row['error']}" if row["error"] else f"{row['n_results']} results"
            print(f"{q['id']} run{run}: {status} ({row['seconds']}s)")
            rows.append(row)
            time.sleep(pause)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare web search tools (no LLM)")
    parser.add_argument("--tool", required=True, choices=sorted(TOOLS))
    parser.add_argument("--settings", required=True, help="settings version, e.g. v1")
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--query", default="all", help="'all' or one query id, e.g. sokhna_q1")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    rows = compare(args.tool, args.settings, args.runs, args.query, args.notes)
    print("\nSummary")
    for line in summarize(rows):
        print("  " + line)


if __name__ == "__main__":
    main()
