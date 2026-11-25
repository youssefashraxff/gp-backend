# Plan: Phase 1 — Research

Status: **draft 5** (merging this PR = approved) · Date: 2026-11-26
Reads: [`spec.md`](spec.md) · Follows: `.claude/skills/gp-system-design`

How to read this file:
- **Sections 1–2:** the decisions this plan is built on, and what must be ready first.
- **Experiments:** the first sprint. Before building any agent, we find out in plain Python
  what works for it (model, prompt, tools, pattern). The results decide its spec section.
- **Sections 3–8:** the work, in groups. Each task says what to build, where, what it
  depends on, and what "done" means (the test that proves it).
- **Section 9:** the risks.

A task is done when its PR is merged into `develop` after review. A task starts only when
everything in its "Depends on" column is done.

---

## 1. Decisions this plan uses

| Topic | Decision |
|---|---|
| LLM models | **Mixed per agent:** each agent's owner picks a cheap and a strong model through the shared routing layer (A4), and writes the choice in their agent's spec section. |
| Web search | **Tavily**, for the Market and Segments agents. |
| Map (frontend) | **Google Maps JS** (`@angular/google-maps`), with satellite view for seeing the land. |
| Escalation scorer | Built as a separate parallel track. Until it's trained, the rule decides: missing or conflicting sources → escalate. |
| Sprint order | **First sprint: experiments** (X0–X6, plus A3 and the keys P2–P4, which the experiments need). **Then the build:** sections 3–8 with LangChain/LangGraph, memory, database, checkpoints and the frontend. Seminar 2 covers Phase 1 only. |
| Agent design | Each owner first runs their agent's experiment (X1–X6) on the shared test sites. With the results, the owner updates that agent's section 6 in spec.md (pattern, model, tools, stop rule → `Status: decided`) in a small PR. Read spec section 5.9 (shared state, the Supervisor's review loop, the three quality layers) and the "Guidance for owners" at the top of spec section 6 first. |
| Quality checks | Every agent runs the code checks (schema + `check_evidence`). Extra LLM checks go only into the data-gathering agents; cross-agent review is the Supervisor's job (spec section 5.9). |

## 2. Before starting

| # | What |
|---|---|
| P1 | gp-schemas PR #3, the spec PR (#11) and the "remove Ruff from CI" PR (#12) are merged ✅ |
| P2 | A Google Cloud project with billing and a **restricted key** for Places API (New), Elevation API and Maps JavaScript API, plus a budget alert on the account. |
| P3 | A Tavily API key. |
| P4 | LLM keys for the providers the agent owners choose. |
| P5 | The Supabase Postgres connection string in `.env` for the checkpointer (`.env.example` updated, real values never committed). |

---

## Experiments (first sprint)

Plain Python in [`experiments/`](../../../experiments/README.md), with no LangChain or
LangGraph. Every run is kept and logged, so old and new versions can be compared. An
experiment is done when its agent passes all test sites (every fact has evidence, the
expected facts are found, the `must_escalate` facts escalate) and the owner has opened the
PR that updates the agent's section 6 in spec.md to `Status: decided`, with the results.

| # | Task | Where | Depends on | Done when |
|---|---|---|---|---|
| X0 | **Test set and scoring:** 3–5 fixed test sites (ideally from Ali's past concepts, mixing dense city, new city and desert road), each with what a good output looks like per agent and what must escalate; agent-specific checks added to `scoring.py` | `experiments/test_sites/`, `experiments/shared/scoring.py` | — | The site files are reviewed (with Ali if possible) and `--site all` runs on them |
| X1 | **Site analysis experiment:** OSM + elevation data quality, the computed facts, the summary prompt and model | `experiments/site_analysis/` | X0, A3 | Passes all test sites; spec 6.1 PR opened with the results |
| X2 | **Market research experiment:** Tavily queries, the 6-call limit, synthesis prompt and model; propose Q9 with the Gap owner | `experiments/market_research/` | X0, A3 | Passes all test sites; spec 6.2 PR opened with the results |
| X3 | **Gap analysis experiment:** prompt and model over saved Site + Market outputs, no tools | `experiments/gap_analysis/` | X0, first X1 + X2 runs | Passes all test sites; spec 6.3 PR opened with the results |
| X4 | **Segments experiment:** demographic sources, the 5-call limit, escalation instead of estimates | `experiments/segments/` | X0, A3, first X3 runs | Passes all test sites; spec 6.4 PR opened with the results |
| X5 | **Competitors experiment:** the density radius on each kind of site, Places quality, classification model | `experiments/competitors/` | X0, A3 | Passes all test sites; spec 6.5 PR opened with the results |
| X6 | **Supervisor experiment:** single reviewer vs critic/debate on saved outputs of the other five, including planted problems | `experiments/supervisor/` | X0, first runs of X1–X5 | Catches the planted problems; spec 6.6 PR opened with the results |

**When an output is bad, change one thing at a time, in this order:** prompt → tools and
data → model → pattern (for example, adding a critic). The reason for each change goes in
the run's notes.

## 3. Foundations

Everything else builds on these.

| # | Task | Where | Depends on | Done when |
|---|---|---|---|---|
| A1 | Bump the schemas submodule, regenerate the types, and rename the progress fields everywhere (workflow query, heartbeat, `ProgressEvent`) | `schemas/`, `app/shared/schemas_generated/`, `app/orchestrator/`, `app/api/progress.py`, `app/api/websocket.py`, tests | P1 | The schema check passes; the existing progress and workflow tests pass with the new names |
| A2 | Frontend: bump the schemas submodule and regenerate the types | gp-frontend `schemas/`, `src/app/shared/schemas/` | P1 | Frontend CI passes |
| A3 | Shared tool clients: Google Places (nearby search + details), Overpass (OSM), Tavily, Google Elevation. Each with its timeout, retries on timeout/429/5xx, throttling and caching (spec section 5.6) | `app/shared/tools/` | P2, P3 | Unit tests with **recorded responses** (no network in CI); one test per client for "times out → retries → gives up cleanly" |
| A4 | Model routing: `get_model(tier, agent)` returns the agent's configured cheap or strong model through LangChain's model interface; responses cached by input hash | `app/shared/models/` | P4 | A test with a fake model gets the right tier, and a repeated call hits the cache |
| A5 | Evidence helpers: build a `Fact` (with its `Evidence`), and `check_evidence(output)`, which lists every fact without evidence | `app/shared/evidence.py` | A1 | Tests: a complete output passes; a missing source is reported with its path |
| A6 | The real research graph: six nodes (stubs at first) in the spec order, parallel branches with reducers, `progress_agent` on every node, output in the `research_output` shape, and the Postgres checkpointer. Replaces the current stub | `app/phases/research/graph.py`, `interface.py` | A1, A5, A7 | A run with all stubs finishes and passes `check_evidence`; the progress test sees all six agents in order; the stub's made-up `"share": 0.4` is gone |
| A7 | Supabase migration: the `escalations` table (matching the escalation schema) and the LangGraph checkpointer tables | `supabase/migrations/` | P5 | The migration applies on a fresh database; a test saves and reads an escalation |

## 4. The six agents

Each agent replaces its stub node in A6. Its owner first updates the agent's spec section
(see section 1, "Agent design").

| # | Agent | Depends on | Done when |
|---|---|---|---|
| B1 | **Site analysis** (spec section 6.1): roads and access from OSM, distances and sun path computed, elevation, and zoning always escalated | X1, A3, A6 | Unit tests with known answers for the distance and sun-path functions; recorded Overpass data; "empty OSM → escalates" |
| B2 | **Market research** (spec section 6.2): Tavily searches, at most 6 tool calls | X2, A3, A4, A6 | Recorded Tavily responses; "conflicting sources → escalates"; every summary sentence cites a fact |
| B3 | **Gap analysis** (spec section 6.3): one structured LLM step with no tools, then the evidence check. Settle Q9 (supply-side data) with the Market owner first | X3, A4, A6 | "A gap without evidence is rejected"; a fixed input gives a stable structure |
| B4 | **Segments** (spec section 6.4): at most 5 tool calls | X4, A3, A4, A6 | "No demographic source → escalates"; "no share without evidence" |
| B5 | **Competitors** (spec section 6.5): the radius computed from local density | X5, A3, A4, A6 | Unit tests for `competitor_radius` (dense street vs desert road); recorded Places data; "zero results → escalates" |
| B6 | **Supervisor** (spec section 6.6): reads the whole state; deterministic checks, then the LLM review (single reviewer first; debate only if tests show misses); feedback through `supervisor_feedback`; reruns the flagged agent and its dependents; at most 2 rerun rounds | X6, A4, A6 | "A fact without evidence triggers a rerun"; "a Gap issue reruns Gap, Segments and Competitors, but not Site or Market"; "a Segments issue doesn't rerun Competitors"; the stop rule holds at 2 rounds |

Agents B1–B6 don't depend on each other's code, so they can be built at the same time.

## 5. Live escalation

| # | Task | Where | Depends on | Done when |
|---|---|---|---|---|
| C1 | Escalation helper: build the payload (question, context with sources, 2–4 choices), save it, then call `interrupt()` | `app/shared/hitl/` | A6, A7 | A test node escalates and the escalation row is saved |
| C2 | Workflow: `waiting_for_expert`, the `expert_answer` signal, a reminder after 30 min, stop after 24 h, and a `resume_phase` activity using `Command(resume=…)` | `app/orchestrator/` | C1 | Temporal tests with the fakes: an answer resumes from the paused node, not from the start; no answer → reminded → `timed_out` |
| C3 | Routes: `GET /concept/{id}/escalation/{escalation_id}` and `POST …/answer` | `app/api/routes/` | C2 | API tests: get the question; the answer sends the signal; a second answer is rejected |

## 6. Edit and rerun

| # | Task | Where | Depends on | Done when |
|---|---|---|---|---|
| D1 | `PATCH /concept/{id}/phase/research/field/{field_path}`: save a new version with the user's value as an `expert` fact, then rerun the dependents (spec section 5.5), skipping nodes whose input hashes didn't change | `app/api/routes/`, `app/orchestrator/`, `app/phases/research/` | A6 | Tests: editing `gaps` reruns segments, competitors and supervisor, but not site or market; every rerun saves a new version |
| D2 | `GET /concept/{id}/phase/research`: the latest result with all its evidence | `app/api/routes/` | A6 | API test |

## 7. Frontend (gp-frontend)

| # | Task | Depends on | Done when |
|---|---|---|---|
| E1 | **GP UI design system** with the ui-craft skill: brand brief → 3 directions → one is chosen → tokens | — | A direction is chosen; tokens are in `src/styles/` and pass the contrast script |
| E2 | **App shell:** a left sidebar of chats, the chat in the centre, a right sidebar with Sources and Documents tabs | E1 | Matches the agreed layout; keyboard-navigable; renders well at 320 / 768 / 1024 / 1440 px |
| E3 | **Site input:** the centred "Enter or drop the location on map" start, Google Maps with satellite view, drop a pin, optional business types, `POST /concept` | E2, A2, P2 | A pin starts a run; the request matches `concept_input`; the map key is restricted |
| E4 | **Live progress in the chat** over the WebSocket: which agent is working and its step | E2, A1 | A visible change at least every ~5 s during a run; survives a disconnect and reconnect |
| E5 | **Summary cards + Sources tab:** one card per agent; clicking a claim opens its source details and a link to the original | E2, D2 | Every claim on a card opens a source (acceptance criterion 4) |
| E6 | **Escalation question card:** the question, context, choices and free text; send the answer | E4, C3 | Answering resumes the run, and progress continues |
| E7 | **Edit and rerun:** edit a result field from its card; affected cards show "rerunning", then update | E5, D1 | Editing a field reruns only its dependents (acceptance criterion 3) |
| E8 | **Documents tab:** this chat's input and output documents | E2, D2 | The input and the research result are listed and open |

## 8. Finish

| # | Task | Depends on | Done when |
|---|---|---|---|
| F1 | End-to-end test on one fixed recorded site: input → six agents → an escalation answered → an edit → rerun | All of sections 3–6 | The test passes in CI without network |
| F2 | **Live test with the domain expert:** a site the expert picks, a live escalation, an edit, and the sources clicked | F1, all of section 7 | The four acceptance criteria are checked off in intent.md |

If something must be cut, follow the spec's scope ranking (spec section 4): Could items first,
then Should. The Must items are never cut, because they are the acceptance criteria.

## 9. Risks

| Risk | Effect | What we do |
|---|---|---|
| Google billing | Unexpected cost | A restricted key and a budget alert (P2); Places results are cached (A3) |
| Egyptian demographic data is often missing | Segments escalates a lot | Expected: it's the planned live escalation for F2 |
| Two versions of the research output schema | Agents built against different shapes | All agents build against `research_output` from gp-schemas; any refinement goes through a gp-schemas PR first |
| Temporal + LangGraph pause and resume is new to the team | C2 is harder than it looks | C2 starts as soon as C1 lands, with pairing on it |
| External APIs change or rate-limit | Flaky runs | Recorded responses in tests; retries and throttling in A3; escalation when a source fails |
| Gap analysis runs before Competitors (supply side) | Gaps that aren't real gaps | Q9 in spec section 7, settled before B3 starts |
| Experiments never end | The build starts late | X0 fixes what "good" means first; each experiment ends when its agent passes the test sites, not when it's perfect. Time-boxed to the first sprint |
| Test sites too easy or too few | The chosen design fails on Ali's live site (F2) | Mix site types in X0 (dense city, new city, desert road); include one site with known missing data |
| The Supervisor only sees the state | A cited but misread source passes review | Careful sourcing and escalation inside the data-gathering agents (spec section 5.9, layer 2) |
