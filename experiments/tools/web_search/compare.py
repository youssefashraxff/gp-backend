"""Call web search tools on fixed queries and save the raw responses. No LLM, no scoring.

The same fixed queries (`queries.json`) go to a tool several times. Every response is saved
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


def load_queries(base_dir: Path = BASE_DIR) -> dict[str, Any]:
    return json.loads((base_dir / "queries.json").read_text(encoding="utf-8"))


def load_settings(tool: str, version: str, base_dir: Path = BASE_DIR) -> dict[str, Any]:
    path = base_dir / "settings" / f"{tool}_{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"No settings '{version}' for {tool} at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------
# Calling and saving
# ---------------------------------------------------------------------------------------


def runs_dir(base_dir: Path, tool: str, settings_version: str) -> Path:
    """One folder per tool and settings version: runs/<tool>/<settings>/."""
    return base_dir / "runs" / tool / settings_version


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
    name = f"{stamp}__{tool}__{settings_version}__{q['id']}__run{run}.json"
    return save_run(
        runs_dir(base_dir, tool, settings_version),
        name,
        {
            "timestamp": now.isoformat(),
            "tool": tool,
            "settings_version": settings_version,
            "settings": settings,
            "query_version": query_version,
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


def compare(
    tool: str,
    settings_version: str,
    runs: int = DEFAULT_RUNS,
    query: str = "all",
    notes: str = "",
    base_dir: Path = BASE_DIR,
    pause: float = PAUSE_SECONDS,
) -> list[Path]:
    if tool not in TOOLS:
        raise SystemExit(f"Unknown tool '{tool}'. Known: {', '.join(TOOLS)}")
    settings = load_settings(tool, settings_version, base_dir)
    queries = load_queries(base_dir)
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
    parser.add_argument("--query", default="all", help="'all' or one query id, e.g. sokhna_q1")
    parser.add_argument("--notes", default="", help="what this run tries; saved in each file")
    args = parser.parse_args()

    paths = compare(args.tool, args.settings, args.runs, args.query, args.notes)
    print(f"\nSaved {len(paths)} run files. Score them with:")
    print("  python -m experiments.tools.web_search.score")


if __name__ == "__main__":
    main()
