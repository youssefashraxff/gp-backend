"""The contract every phase module follows.

Rule: other code may import ONLY a phase's `interface.py`. Nothing reaches
into another phase's agents, graphs or helpers.

Each interface.py exposes:
  NAME   -- the phase name
  READS  -- declared field dependencies, e.g. "research.target_segments"
            (checked against the reads recorded at run time)
  run()  -- runs the phase's LangGraph and returns its output fields
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

PhaseOutput = dict[str, Any]
RunPhase = Callable[[str, dict[str, Any]], Awaitable[PhaseOutput]]


class PhaseInterface(Protocol):
    NAME: str
    READS: tuple[str, ...]

    async def run(self, concept_id: str, inputs: dict[str, Any]) -> PhaseOutput: ...
