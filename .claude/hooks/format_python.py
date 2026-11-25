#!/usr/bin/env python3
"""PostToolUse hook (Edit/Write): tidy the edited Python file with Ruff.

Never blocks: it fixes what it can quietly, so style never becomes a review topic.
Unused imports (F401) are left alone: Claude often adds an import one edit before using it.
"""
import json
import shutil
import subprocess
import sys

data = json.load(sys.stdin)
path = data.get("tool_input", {}).get("file_path", "")
ruff = shutil.which("ruff")
if path.endswith(".py") and ruff:
    subprocess.run([ruff, "check", "--fix", "--unfixable", "F401", "--quiet", path], capture_output=True, timeout=60)
    subprocess.run([ruff, "format", "--quiet", path], capture_output=True, timeout=60)
sys.exit(0)
