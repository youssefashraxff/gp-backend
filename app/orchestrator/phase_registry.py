"""Map phase names to their public interfaces.

The orchestrator uses PHASE_REGISTRY to look up a phase by name and
call its run() function. Each registry entry uses the phase's NAME
as its key and its interface module as its value.

To register a new phase, import its interface.py module and add it
to PHASE_REGISTRY. Keep graphs, agents, and helpers inside the phase
package.
"""

from app.phases.research import interface as research
from app.shared.phase_contract import PhaseInterface

PHASE_REGISTRY: dict[str, PhaseInterface] = {
    research.NAME: research,
}