#!/usr/bin/env python3
"""PreToolUse hook (Bash): block git commands that skip the PR flow.

Blocks: pushing to main/develop, force pushes, and committing while on main/develop.
Exit 2 = block; the message on stderr goes back to Claude.
"""
import json
import re
import subprocess
import sys

data = json.load(sys.stdin)
cmd = data.get("tool_input", {}).get("command", "")


def block(msg: str) -> None:
    print(f"Blocked by repo hook: {msg}", file=sys.stderr)
    sys.exit(2)


for part in re.split(r"&&|\|\||;|\n", cmd):
    p = part.strip()
    if re.search(r"\bgit\b.*\bpush\b", p):
        if re.search(r"--force(?!-with-lease)\b|\s-f\b", p):
            block("no force pushes. Push a new commit instead.")
        if re.search(r"\b(main|develop)\b", p) and not re.search(r"\b(feature|fix|docs|chore|design)/", p):
            block("no direct pushes to main or develop. Push your branch and open a PR into develop.")
    if re.search(r"\bgit\b.*\bcommit\b", p):
        try:
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except Exception:
            branch = ""
        if branch in ("main", "develop"):
            block(f"you're on '{branch}'. Create a branch from develop first "
                  "(feature/<clickup-id>-short-name or fix/<clickup-id>-short-name).")
sys.exit(0)
