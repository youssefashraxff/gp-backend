"""Content hashing for field-level edit propagation.

A field is stale only if the hash of what it was built from changed.
Hashing canonical JSON means key order and whitespace never cause
false "changes".
"""

import hashlib
import json
from typing import Any


def content_hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
