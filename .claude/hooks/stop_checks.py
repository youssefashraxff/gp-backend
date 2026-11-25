#!/usr/bin/env python3
"""Stop hook: before Claude says it's done, the tests must pass.

Runs only when Python files under app/ or tests/ changed. If pytest fails, exit 2 sends the
failure back to Claude so it keeps working instead of stopping.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

data = json.load(sys.stdin)
if data.get("stop_hook_active"):
    sys.exit(0)  # already continuing because of this hook: don't loop forever

root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ".")
changed = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                         capture_output=True, text=True).stdout.splitlines()
if not any(ln[3:].startswith(("app/", "tests/")) and ln.endswith(".py") for ln in changed):
    sys.exit(0)

venv_py = root / ".venv/bin/python"
python = str(venv_py) if venv_py.exists() else sys.executable
env = {**os.environ}
env.setdefault("TEMPORAL_ADDRESS", "localhost:7233")  # same defaults as CI
env.setdefault("TEMPORAL_NAMESPACE", "default")
try:
    r = subprocess.run([python, "-m", "pytest", "-q", "-x"], cwd=root, env=env,
                       capture_output=True, text=True, timeout=600)
except subprocess.TimeoutExpired:
    print("Tests took over 10 minutes; check for a hanging test before finishing.", file=sys.stderr)
    sys.exit(2)
if r.returncode not in (0, 5):  # 5 = no tests collected
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-40:])
    print(f"Tests are failing. Fix them (or explain why) before finishing:\n{tail}", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
