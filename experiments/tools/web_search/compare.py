"""Call web search tools on fixed queries and save the raw responses. No LLM, no scoring.

The same fixed queries (`queries.json` = v1 English, `queries_v2.json` = v2 Arabic; pick
with `--queries`) go to a tool several times. Every response is saved
to `runs/` (one new file per call, never overwritten). Counting and comparing happens
afterwards in `score.py`, which reads only these files, so changing a source list and
rescoring never needs another API call.

Run:
    python -m experiments.tools.web_search.compare --tool tavily --settings v1 \
        --query all --notes "first baseline"
    python -m experiments.tools.web_search.score

Add a tool: write one `search_<tool>(query, settings)` function, register it in `TOOLS`,
and add `settings/<tool>_v1.json`.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_RUNS = 2
PAUSE_SECONDS = 0.5
TIMEOUT_SECONDS = 30

STATUS_OK = "ok"
STATUS_EMPTY = "empty"  # no error, but 0 results even after one retry
STATUS_ERROR = "error"


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
# Inputs
# ---------------------------------------------------------------------------------------


DEFAULT_QUERIES = "v1"


def queries_path(version: str, base_dir: Path = BASE_DIR) -> Path:
    """v1 is `queries.json` (the original file, kept as it is); later versions are
    `queries_<version>.json`."""
    name = "queries.json" if version == "v1" else f"queries_{version}.json"
    return base_dir / name


def load_queries(version: str = DEFAULT_QUERIES, base_dir: Path = BASE_DIR) -> dict[str, Any]:
    path = queries_path(version, base_dir)
    if not path.exists():
        raise FileNotFoundError(f"No queries '{version}' at {path}")
    queries = json.loads(path.read_text(encoding="utf-8"))
    if queries.get("version") != version:
        raise ValueError(f"{path.name} says version {queries.get('version')!r}, not {version!r}")
    return queries


def load_settings(tool: str, version: str, base_dir: Path = BASE_DIR) -> dict[str, Any]:
    path = base_dir / "settings" / f"{tool}_{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"No settings '{version}' for {tool} at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------
# Calling and saving
# ---------------------------------------------------------------------------------------


def runs_dir(base_dir: Path, tool: str, settings_version: str, query_version: str) -> Path:
    """One folder per tool, settings version and query version:
    runs/<tool>/<settings>/queries_<version>/."""
    return base_dir / "runs" / tool / settings_version / f"queries_{query_version}"


def save_run(folder: Path, name: str, payload: dict[str, Any]) -> Path:
    """Write a new run file. Mode "x" refuses to overwrite an existing file."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    with path.open("x", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    return path


def _call(tool: str, query: str, settings: dict[str, Any]) -> dict[str, Any]:
    """One call. Never raises: a failure is returned as `error`."""
    start = time.perf_counter()
    raw: Any = None
    results: list[Result] = []
    error = ""
    try:
        raw, results = TOOLS[tool](query, dict(settings))
    except Exception as exc:  # noqa: BLE001 (any failure is a result to record, not a crash)
        error = f"{type(exc).__name__}: {exc}"
    return {
        "raw": raw,
        "results": results,
        "error": error,
        "seconds": round(time.perf_counter() - start, 3),
    }


def run_once(
    tool: str,
    settings_version: str,
    settings: dict[str, Any],
    query_version: str,
    q: dict[str, str],
    run: int,
    notes: str = "",
    base_dir: Path = BASE_DIR,
    pause: float = PAUSE_SECONDS,
    query_language: str | None = None,
) -> Path:
    """Call the tool (retrying once if it returns 0 results without an error) and save the
    response to a new run file. Returns the file's path."""
    now = datetime.now(UTC)
    attempts = [_call(tool, q["query"], settings)]
    if not attempts[0]["error"] and not attempts[0]["results"]:
        time.sleep(pause)
        attempts.append(_call(tool, q["query"], settings))
    final = attempts[-1]
    if final["error"]:
        status = STATUS_ERROR
    elif not final["results"]:
        status = STATUS_EMPTY
    else:
        status = STATUS_OK

    # Time first, so sorting by name is sorting by time.
    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    name = f"{stamp}__{tool}__{settings_version}__q{query_version}__{q['id']}__run{run}.json"
    return save_run(
        runs_dir(base_dir, tool, settings_version, query_version),
        name,
        {
            "timestamp": now.isoformat(),
            "tool": tool,
            "settings_version": settings_version,
            "settings": settings,
            "query_version": query_version,
            "query_language": query_language,
            "query": q,
            "run": run,
            "status": status,
            "attempts": len(attempts),
            "seconds": final["seconds"],
            "error": final["error"] or None,
            "notes": notes,
            "normalized": [asdict(r) for r in final["results"]],
            "raw_response": final["raw"],
        },
    )


# ---------------------------------------------------------------------------------------
# Strategies: several searches per question, saved together in one run file
# ---------------------------------------------------------------------------------------
#
# A strategy settings file looks like:
#   {"strategy": "mixed",
#    "base": {...tool settings shared by every search...},
#    "searches": [{"name": "ar_restricted", "queries": "v2", ...extra tool settings...}, ...]}
# Each search uses the text of the same question id from its own query version.


def _search_params(settings: dict[str, Any], search: dict[str, Any]) -> dict[str, Any]:
    extra = {k: v for k, v in search.items() if k not in ("name", "queries")}
    return {**settings.get("base", {}), **extra}


def _url_key(url: str) -> str:
    return url.strip().rstrip("/").lower()


def merge_results(searches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by URL across searches, keeping which searches found each URL.
    Ordered by the best score any search gave the URL (no score last), then first seen."""
    merged: dict[str, dict[str, Any]] = {}
    for search in searches:
        for result in search["normalized"]:
            key = _url_key(result["url"])
            if key not in merged:
                merged[key] = {**result, "found_by": [search["name"]]}
                continue
            entry = merged[key]
            if search["name"] not in entry["found_by"]:
                entry["found_by"].append(search["name"])
            if result.get("score") is not None and (
                entry.get("score") is None or result["score"] > entry["score"]
            ):
                entry["score"] = result["score"]
            if not entry.get("published_date") and result.get("published_date"):
                entry["published_date"] = result["published_date"]
    order = {key: i for i, key in enumerate(merged)}
    return sorted(
        merged.values(),
        key=lambda r: (r.get("score") is None, -(r.get("score") or 0), order[_url_key(r["url"])]),
    )


def run_strategy_once(
    tool: str,
    settings_version: str,
    settings: dict[str, Any],
    query_version: str,
    question: dict[str, Any],
    run: int,
    notes: str = "",
    base_dir: Path = BASE_DIR,
    pause: float = PAUSE_SECONDS,
) -> Path:
    """Make every search of the strategy for one question and save ONE run file with each
    search's raw response (labelled by name) and the merged results.

    A restricted search (include_domains_mode "restrict") that finds nothing is normal, so it
    is saved as `empty` without a retry; an open search that comes back empty is retried once.
    """
    now = datetime.now(UTC)
    searches = []
    for i, search in enumerate(settings["searches"]):
        if i:
            time.sleep(pause)
        params = _search_params(settings, search)
        text = question["queries"][search["name"]]
        attempts = [_call(tool, text, params)]
        restricted = params.get("include_domains_mode") == "restrict"
        if not restricted and not attempts[0]["error"] and not attempts[0]["results"]:
            time.sleep(pause)
            attempts.append(_call(tool, text, params))
        final = attempts[-1]
        status = STATUS_ERROR if final["error"] else STATUS_OK if final["results"] else STATUS_EMPTY
        searches.append(
            {
                "name": search["name"],
                "query_version": search["queries"],
                "query": text,
                "status": status,
                "attempts": len(attempts),
                "seconds": final["seconds"],
                "error": final["error"] or None,
                "normalized": [asdict(r) for r in final["results"]],
                "raw_response": final["raw"],
            }
        )

    merged = merge_results(searches)
    errors = [f"{s['name']}: {s['error']}" for s in searches if s["error"]]
    if len(errors) == len(searches):
        status = STATUS_ERROR
    else:
        status = STATUS_OK if merged else STATUS_EMPTY

    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    name = f"{stamp}__{tool}__{settings_version}__q{query_version}__{question['id']}__run{run}.json"
    return save_run(
        runs_dir(base_dir, tool, settings_version, query_version),
        name,
        {
            "timestamp": now.isoformat(),
            "tool": tool,
            "settings_version": settings_version,
            "settings": settings,
            "strategy": settings["strategy"],
            "query_version": query_version,
            "query": {k: question[k] for k in ("id", "site", "group")},
            "run": run,
            "status": status,
            "seconds": round(sum(s["seconds"] for s in searches), 3),
            "error": "; ".join(errors) or None,
            "notes": notes,
            "searches": searches,
            "normalized": merged,
        },
    )


def load_strategy_questions(
    settings: dict[str, Any], base_dir: Path = BASE_DIR
) -> tuple[str, list[dict[str, Any]]]:
    """(query_version label, questions). Each question has id, site, group and the text
    every search will send ({search name: query text})."""
    versions = sorted({s["queries"] for s in settings["searches"]})
    files = {v: load_queries(v, base_dir) for v in versions}
    by_id = {v: {q["id"]: q for q in f["queries"]} for v, f in files.items()}
    first = settings["searches"][0]["queries"]
    ids = [q["id"] for q in files[first]["queries"]]
    for v in versions:
        if set(by_id[v]) != set(ids):
            raise ValueError(f"Query versions {first} and {v} don't have the same ids")
    questions = [
        {
            **{k: by_id[first][qid][k] for k in ("id", "site", "group")},
            "queries": {s["name"]: by_id[s["queries"]][qid]["query"] for s in settings["searches"]},
        }
        for qid in ids
    ]
    return "+".join(versions), questions


def compare_strategy(
    tool: str,
    settings_version: str,
    settings: dict[str, Any],
    runs: int,
    query: str,
    notes: str,
    base_dir: Path,
    pause: float,
) -> list[Path]:
    query_version, questions = load_strategy_questions(settings, base_dir)
    selected = [q for q in questions if query in ("all", q["id"])]
    if not selected:
        raise SystemExit(f"Unknown query '{query}'")
    paths = []
    for q in selected:
        for run in range(1, runs + 1):
            path = run_strategy_once(
                tool, settings_version, settings, query_version, q, run, notes, base_dir, pause
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
            parts = ", ".join(
                f"{s['name']} {s['status']} {len(s['normalized'])}" for s in saved["searches"]
            )
            print(
                f"{q['id']} run{run}: {saved['status']}, merged {len(saved['normalized'])} "
                f"({parts}) ({saved['seconds']}s)"
            )
            paths.append(path)
            time.sleep(pause)
    return paths


def compare(
    tool: str,
    settings_version: str,
    runs: int = DEFAULT_RUNS,
    query: str = "all",
    notes: str = "",
    base_dir: Path = BASE_DIR,
    pause: float = PAUSE_SECONDS,
    query_version: str = DEFAULT_QUERIES,
) -> list[Path]:
    """Run plain searches, or a strategy if the settings file defines one (then the
    strategy picks the query versions and `query_version` is ignored)."""
    if tool not in TOOLS:
        raise SystemExit(f"Unknown tool '{tool}'. Known: {', '.join(TOOLS)}")
    settings = load_settings(tool, settings_version, base_dir)
    if settings.get("strategy"):
        return compare_strategy(
            tool, settings_version, settings, runs, query, notes, base_dir, pause
        )
    queries = load_queries(query_version, base_dir)
    selected = [q for q in queries["queries"] if query in ("all", q["id"])]
    if not selected:
        raise SystemExit(f"Unknown query '{query}'")

    paths = []
    for q in selected:
        for run in range(1, runs + 1):
            path = run_once(
                tool,
                settings_version,
                settings,
                queries["version"],
                q,
                run,
                notes,
                base_dir,
                pause,
                queries.get("language"),
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
            detail = saved["error"] or f"{len(saved['normalized'])} results"
            print(f"{q['id']} run{run}: {saved['status']}, {detail} ({saved['seconds']}s)")
            paths.append(path)
            time.sleep(pause)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Call a web search tool and save raw runs")
    parser.add_argument("--tool", required=True, choices=sorted(TOOLS))
    parser.add_argument("--settings", required=True, help="settings version, e.g. v1")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument(
        "--queries",
        default=DEFAULT_QUERIES,
        help="query version: v1 = queries.json (English), v2 = queries_v2.json (Arabic)",
    )
    parser.add_argument("--query", default="all", help="'all' or one query id, e.g. sokhna_q1")
    parser.add_argument("--notes", default="", help="what this run tries; saved in each file")
    args = parser.parse_args()

    paths = compare(
        args.tool, args.settings, args.runs, args.query, args.notes, query_version=args.queries
    )
    print(f"\nSaved {len(paths)} run files. Score them with:")
    print("  python -m experiments.tools.web_search.score")


if __name__ == "__main__":
    main()
