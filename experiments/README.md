# Phase 1 experiments

Before we build the agents with LangChain and LangGraph, we find out **what works** for each
one: the best model, prompt, tools and pattern. This folder is where we try things in plain
Python. The results decide each agent's section 6 in
[`docs/sdlc/phase-1/spec.md`](../docs/sdlc/phase-1/spec.md), and the build sprint then
builds exactly that.

This is not production code: nothing under `app/` imports from `experiments/`.

## Layout

```
experiments/
  test_sites/          the fixed test sites, shared by everyone (task X0)
    site_template.json copy it to site_01.json, site_02.json, ...
  shared/
    runner.py          runs an agent on a site, saves the output, logs a results row
    scoring.py         the checks every output gets (evidence coverage, escalations)
  <agent>/             site_analysis, market_research, gap_analysis, segments,
                       competitors, supervisor
    run.py             the experiment code for this agent (the owner writes it)
    prompts/v1.md      one file per prompt version
    runs/              every run's full output, one new file per run
    results.csv        one row per run
```

## How to run

```bash
python -m experiments.market_research.run --site site_01 --prompt v1 --model <model>
python -m experiments.market_research.run --site all --prompt v2 --model <model> \
    --tools "tavily" --pattern "tool-calling, max 6 calls" --notes "added Vision 2030 query"
```

Each run saves its output to `runs/` and adds a row to `results.csv`.

## Rules

1. **Never delete or overwrite a version.** A new prompt is a new file (`v2.md`), never an
   edit of `v1.md` after it has been run. Every run gets its own file in `runs/`. Old and
   new must always be comparable.
2. **Change one thing at a time** between runs, and say what changed in `--notes`. When an
   output is bad, try fixes in this order:
   1. the prompt (cheapest);
   2. the tools and data (in Egypt, missing data is the most common cause);
   3. the model;
   4. the pattern, e.g. adding a critic (most expensive, so last).
3. **Run on every test site** (`--site all`) before calling a version better. One good site
   proves nothing.
4. **No estimated facts, even here.** Every fact has a type and a source; when the source is
   missing, the output records an escalation instead. `evidence_coverage` must be `1.0`.
5. **Agents that read other agents' outputs** (Gap analysis, Segments, Supervisor) use
   `load_latest_output(agent, site_id)`, so they don't wait for those agents to be finished.
6. **API keys come from `.env`** and are never committed. Use the shared tool clients from
   `app/shared/tools/` (plan A3) when they exist, so experiments and production call the
   APIs the same way.
7. **Commit `runs/` and `results.csv`.** They are the evidence for the decisions, and good
   material for the seminar and the report.

## Output shape

Every `run.py` returns the shape described at the top of
[`shared/scoring.py`](shared/scoring.py): `facts` (each with `type` and `evidence`),
`escalations`, `summary` and `cost_usd`. It becomes the gp-schemas `research_output`
shape once plan A1 lands.

## When an agent's experiment is done

The agent passes all test sites (`evidence_coverage` 1.0, the expected facts from its test
site files present, the `must_escalate` facts escalated). Then the owner opens the PR that
updates the agent's section 6 in `spec.md` with the chosen model, prompt version, tools,
pattern and the scores, and sets `Status: decided`.
