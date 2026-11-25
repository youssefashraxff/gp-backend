---
name: gp-architecture
description: The Concept Development GP's system rules (modular monolith, Temporal between phases, LangGraph inside, phase contract, edit propagation, naming). Use when writing or reviewing a spec.md or plan.md, designing a new module, agent or API route, or checking that a change fits the architecture.
---

# GP architecture rules

These rules are decided. A spec or plan must follow them. If a requirement seems to need
breaking one, do not quietly work around it: list it under **Open questions** in the spec
for Youssef to decide.

## 1. Shape: one codebase, two processes

- **Modular monolith.** Everything is in `gp-backend`, with one module per phase under
  `app/phases/<phase>/`.
- **Two processes:**
  - the API (`app/api/main.py`: FastAPI routes and the WebSocket);
  - the worker (`app/worker/main.py`: the Temporal worker that runs the agents).
- The API never runs agents itself. It starts or signals a Temporal workflow and returns
  straight away (`202 Accepted`).

## 2. Who owns what

| Concern | Owner | Where |
|---|---|---|
| Phase order, retries, timeouts, waiting for approval or for the expert | Temporal | `app/orchestrator/` |
| Everything inside a phase: agents, tools, supervisor loop, checkpoints | LangGraph | `app/phases/<phase>/` |
| Saved, versioned phase results | Supabase | `app/shared/db.py` |
| Types shared with the frontend | JSON Schemas | `schemas/` (gp-schemas submodule) |

- Phases run in this order: `research → brand_design → visuals → investment`. A phase starts
  only after the previous one is done and saved.
- **Mid-phase escalation:** LangGraph pauses at a checkpoint, Temporal waits for the
  expert's signal, and the run resumes from that checkpoint. Escalation never restarts the
  phase.

## 3. The phase contract

- Other code may import a phase **only through its `interface.py`**. Nothing reaches into
  another phase's graphs, agents or helpers.
- Each `interface.py` exposes `NAME`, `READS` and `async run(concept_id, inputs, on_progress)`
  (see `app/shared/phase_contract.py`).
- A phase is wired in by adding it to `PHASE_REGISTRY` (`app/orchestrator/phase_registry.py`).
- Phases share data **only through saved phase results**, never by calling each other.
- Code used by more than one phase goes in `app/shared/` (HITL, RAG, tools, model routing).

## 4. Edit propagation

- Propagation is field-level. A phase declares the fields it reads in `READS`, for example
  `"research.target_segments"`, and its reads are also recorded at run time.
- Every saved field carries a `content_hash()` (`app/shared/hashing.py`). A field is stale
  only if the hash of what it was built from changed. An edit that doesn't change a value
  reruns nothing.
- Every rerun saves a new version. It never overwrites the old one.

## 5. Contracts and types

- Any data that crosses the API, the WebSocket or a saved phase result is defined as a JSON
  Schema in **gp-schemas** first. Python and TypeScript types are generated from it
  (`scripts/generate_types.sh`). Never hand-write a duplicate model.
- A spec that adds or changes such data must name the schema file it changes.

## 6. Naming

- **Routes:** use the singular `/concept` to create or get one concept. Use `/concepts` only
  for listing all concepts.
- **Progress names must say which level they describe:**
  - workflow query: `current_phase`, `workflow_status`, `workflow_action`
  - activity heartbeat: `phase_step_agent`, `phase_percent`
  - `ProgressEvent`: `progress_phase`, `progress_status`, `progress_step`, `progress_percent`
  - Never use a bare `step` or `status`. Some older code still does; rename it when you touch it.
- **Branches:** `feature/<clickup-id>-short-name`, `fix/<clickup-id>-short-name`, created
  from `develop`.

## 7. Cost

- Choose models through the model routing in `app/shared/`: a cheap model for simple steps
  and a strong model only where it is needed.
- LangGraph has no token budgets, so budgets and caching are enforced at the model layer.
- A spec that adds an LLM call must say which model tier it uses and why.

## 8. Process

- Merge into `develop` through a PR. Only Youssef merges. Done = merged into `develop`.
- CI must pass: Ruff (lint and format), the schema check, Pyright (basic) and pytest.
- SDLC documents live in `docs/sdlc/<feature>/` (`intent.md`, `spec.md`, `plan.md`).

## Checklist when writing or reviewing a spec

- [ ] Does every new piece of logic have a home: API, orchestrator, a phase, or shared?
- [ ] Does anything cross phases other than saved results through `interface.py`?
- [ ] Does each phase list its `READS`, and does each new output field have a hash?
- [ ] Is every new or changed contract named as a gp-schemas file?
- [ ] Do the names follow section 6?
- [ ] Does each LLM call state its model tier?
- [ ] Is every rule this spec bends listed under **Open questions**?
