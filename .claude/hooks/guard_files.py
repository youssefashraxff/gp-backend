#!/usr/bin/env python3
"""PreToolUse hook (Edit/Write): protect files that must not be edited by hand.

- app/shared/schemas_generated/  generated from gp-schemas
- schemas/                       the gp-schemas submodule
- .env                           secrets
- app/phases/research/agents/<agent>  blocked while that agent's spec section is still draft
Exit 2 = block; the message on stderr goes back to Claude.
"""
import json
import os
import re
import sys
from pathlib import Path

data = json.load(sys.stdin)
raw = data.get("tool_input", {}).get("file_path") or data.get("tool_input", {}).get("notebook_path") or ""
root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ".").resolve()
try:
    rel = Path(raw).resolve().relative_to(root).as_posix()
except ValueError:
    sys.exit(0)  # outside the repo: not ours to judge


def block(msg: str) -> None:
    print(f"Blocked by repo hook: {msg}", file=sys.stderr)
    sys.exit(2)


if rel.startswith("app/shared/schemas_generated/"):
    block("these types are generated. Change the schema in gp-schemas, bump the submodule, "
          "then run: bash scripts/generate_types.sh")
if rel == "schemas" or rel.startswith("schemas/"):
    block("schemas/ is the gp-schemas submodule. Make the change in gp-schemas with a PR, "
          "then bump the submodule here.")
if rel == ".env":
    block(".env holds secrets and is never edited by Claude. Add new variable names to "
          ".env.example and tell the user to fill in .env.")

# Spec gate: an agent's code waits until its spec section says `Status: decided`.
SECTIONS = {
    "site_analysis": "6.1", "market_research": "6.2", "gap_analysis": "6.3",
    "segments": "6.4", "competitors": "6.5", "supervisor": "6.6",
}
m = re.match(r"app/phases/research/agents/([a-z_]+)(\.py$|/)", rel)
if m and m.group(1) in SECTIONS:
    sec = SECTIONS[m.group(1)]
    spec = root / "docs/sdlc/phase-1/spec.md"
    head = next((ln for ln in spec.read_text().splitlines() if ln.startswith(f"### {sec} ")), "") \
        if spec.exists() else ""
    if "Status: decided" not in head:
        block(f"the design of '{m.group(1)}' is not decided yet (spec.md section {sec} says draft). "
              f"First update section {sec} of docs/sdlc/phase-1/spec.md (pattern, model, tools, "
              "stop rule, then 'Status: decided') in its own PR and get it merged, then write the code.")
sys.exit(0)
