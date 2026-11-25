"""Scores every experiment output the same way, so runs can be compared.

These are the checks that apply to every agent. Task X0 (the test set) adds the
agent-specific checks: what a good output looks like for each agent on each test site.

Output shape every experiment returns (it becomes the gp-schemas `research_output` shape
once plan task A1 lands):

    {
      "facts": [
        {"claim": "...", "value": ..., "type": "computable" | "retrieved" | "expert",
         "evidence": {"source": "<url, API + query, function name or escalation id>",
                      "retrieved_at": "<ISO time>"}}
      ],
      "escalations": [{"question": "...", "reason": "...", "choices": ["...", "..."]}],
      "summary": "...",
      "cost_usd": 0.0
    }
"""

from __future__ import annotations

from typing import Any

FACT_TYPES = {"computable", "retrieved", "expert"}


def has_evidence(fact: dict[str, Any]) -> bool:
    """A fact counts as grounded only with a known type and a non-empty source."""
    evidence = fact.get("evidence") or {}
    return fact.get("type") in FACT_TYPES and bool(str(evidence.get("source", "")).strip())


def score_output(output: dict[str, Any]) -> dict[str, Any]:
    facts = output.get("facts") or []
    missing = [f.get("claim", "?") for f in facts if not has_evidence(f)]
    return {
        "facts": len(facts),
        "facts_without_evidence": len(missing),
        "missing_evidence": missing,
        # Share of facts that carry evidence. 1.0 is the only acceptable final value.
        "evidence_coverage": round(1 - len(missing) / len(facts), 3) if facts else 0.0,
        "escalations": len(output.get("escalations") or []),
    }
