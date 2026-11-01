"""Temporal workflows: the flow *between* phases.

Owns: phase order, approval waits between phases, retries/timeouts,
waiting for the expert's answer during a mid-phase escalation (then
resuming from the LangGraph checkpoint), and rerunning stale phases.

Does NOT own anything inside a phase — that is LangGraph, behind each
phase's interface.py.

Phase order (a phase starts only after the previous one is done):
"""

PHASE_ORDER: tuple[str, ...] = ("research", "brand_design", "visuals", "investment")
