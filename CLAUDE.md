# gp-backend: notes for Claude

The backend of the Concept Development GP: a multi-agent system that turns a site in Egypt
into a commercial concept package. When it lacks grounded information it **asks a human
expert instead of guessing**. That claim drives every rule below.

## Read before any task

1. **The SDLC documents for the work:** `docs/sdlc/<phase>/intent.md` (why), `spec.md`
   (what exactly) and `plan.md` (the task list, each task with its "done when"). Find the plan
   task you're working on (e.g. `A3`, `B5`) and build exactly that. Put the task ID in the PR
   title.
2. **The `gp-system-design` skill** (`.claude/skills/gp-system-design/`). Part A holds the
   architecture rules that must not be broken; Part B is the method for designing anything new.
   Use it whenever you write a spec section, a plan, or a new module, agent or route.

If the task, the spec and the code disagree, stop and say so. Don't pick one quietly.

## Commands

```bash
pip install -e ".[dev]"              # install (inside .venv)
docker compose up -d                 # Temporal on :7233, UI on http://localhost:8233
uvicorn app.api.main:app --reload    # API process
python -m app.worker.main            # worker process (runs the agents)
pytest                               # tests (no real network: use recorded responses)
pyright                              # type check (basic)
bash scripts/generate_types.sh       # regenerate types after a schemas submodule bump
```

## Rules that matter most

- **No estimated facts.** Every fact an agent outputs is `computable`, `retrieved` or
  `expert`, and carries its evidence (gp-schemas `evidence`). If a source is missing or
  sources conflict, the agent escalates. An LLM never invents a number.
- **Phases talk only through saved phase results**, and other code imports a phase only
  through its `interface.py`.
- **Temporal workflow code is deterministic:** no I/O, network, `datetime.now()` or
  randomness in `workflows.py`. Put those in activities.
- **Schemas come first.** Any data crossing the API, the WebSocket or a saved result is
  changed in gp-schemas, then the submodule is bumped and the types regenerated. Never
  hand-write a duplicate model.
- **Progress names say their level:** `current_phase`, `workflow_status`, `workflow_action`
  (workflow query); `phase_step_agent`, `phase_percent` (heartbeat); `progress_phase`,
  `progress_status`, `progress_step`, `progress_percent`, `progress_agent` (`ProgressEvent`).
  Never a bare `step` or `status`.
- **Routes:** singular `/concept` for one concept; `/concepts` only lists them.
- **Agents live in `app/phases/research/agents/<agent>.py`** (`site_analysis`,
  `market_research`, `gap_analysis`, `segments`, `competitors`, `supervisor`). Stubs stay in
  `app/phases/research/stubs.py` until the real agent replaces them.
- **Experiments come before agents.** `experiments/` holds the plain-Python experiments
  (plan X0–X6) that decide each agent's design. Nothing under `app/` imports from it. Never
  delete or overwrite a prompt version or a saved run there; add a new one.
- **An agent's design is decided before its code.** Its section 6 in `spec.md` must say
  `Status: decided` first. If the code needs a different design, update the spec first.
- **Tests:** every new piece of logic gets a test. External calls use recorded responses;
  Temporal uses `tests/temporal_fakes.py`.

## Git and PRs

- Branch from `develop`: `feature/<clickup-id>-short-name` or `fix/<clickup-id>-short-name`
  (`docs/…` for documents, `design/<clickup-id>-<agent>-pattern` for spec section updates).
- One plan task per PR, into `develop`. Only the project lead merges.
- Fill in the PR template. "Why" explains the reason for each choice and the alternative
  that wasn't chosen, so the reviewer understands the change, not just sees it.

## Explaining your work

The team wants to understand every change, not just receive it. When you finish a task,
explain **what** you changed, **why** this way and not another, and **how** it works, in plain
language. Explain any new term the first time it appears.

## Hooks in this repo (`.claude/settings.json`)

| Hook | What it does |
|---|---|
| Before an edit | Blocks edits to `app/shared/schemas_generated/`, `schemas/` and `.env`, and agent code whose spec section is still draft |
| Before a shell command | Blocks pushing to `main`/`develop`, force pushes, and committing while on `main`/`develop` |
| After an edit | Tidies the edited Python file with Ruff (never blocks) |
| Before finishing | Runs `pytest` if Python files changed; failing tests send Claude back to fix them |

If a hook blocks you, read its message and follow it. Don't work around it.
