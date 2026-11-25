# Spec: Phase 1 — Research

Status: **draft** (merging this PR = accepted) · Owner: Youssef · Date: 2026-11-25
Reads: [`intent.md`](intent.md) · Follows: `.claude/skills/gp-system-design`

How to read this file:
- **§1–§4:** *what* we build and how we know it's done.
- **§5:** the design of the whole phase.
- **§6:** the design of each agent. Each agent section is a **draft for its owner to
  review and change**: the owner decides the agent's internal pattern, model and cost.
- **§7:** the decisions Youssef still has to make. Anything marked **(proposal)** is not
  decided yet.

---

## 1. Summary

The user drops a pin on a map and can name the business types they're considering. Six
agents research the site:

```
Site analysis ─┐
               ├─► Gap analysis ─► Segments ─┐
Market research┘                 Competitors ┴─► Supervisor ─► Research result
```

Each step streams live into the chat. Every claim links to its source. When an agent lacks
grounded information, it asks the expert mid-task instead of guessing, and then continues.
The user can edit any result; only what depends on the edit reruns.

## 2. Requirements

### Functional

| ID | Requirement |
|---|---|
| FR-1 | **Input:** a site pin (name + lat/lng), optional business type(s), plus the existing optional client name, budget and preferences. |
| FR-2 | **Run:** `POST /concept` starts the run. The six agents run in the order in §1, inside one LangGraph per phase. |
| FR-3 | **Live progress:** the WebSocket streams which agent is working and what it's doing. The user never waits more than ~5 s without a visible change. |
| FR-4 | **Output:** findings from each agent, plus business types recommended by the research (alongside any the user entered). |
| FR-5 | **Evidence:** every fact in the output carries its type (computable / retrieved / expert), its source and its time. No fact is estimated by an LLM. |
| FR-6 | **Live escalation:** any agent can pause mid-task and ask the expert a question with 2–4 suggested answers plus free text. The run resumes from that point with the answer. |
| FR-7 | **Escalation scorer:** a small supervised classifier decides when to escalate. Until it's trained, a rule decides: missing or conflicting sources → escalate. |
| FR-8 | **Edit and rerun:** the user edits a result field; the fields that depend on it rerun; a new version is saved. Fields whose inputs didn't change are not rerun. |
| FR-9 | **Presentation (frontend):** summary cards in the chat, the full report opens in the chat, a Sources tab (the clicked source's details and a link to the original) and a Documents tab (this chat's input/output docs). The screen design is owned by the frontend spec. |

### Non-functional

| ID | Requirement |
|---|---|
| NFR-1 | Follows Part A of gp-system-design (modular monolith, Temporal between phases, LangGraph inside, phase contract, schemas first, naming). |
| NFR-2 | Every external call has a timeout, retry rules and a message the user sees when it fails (§5.6). |
| NFR-3 | Each LLM node states its model tier; strong models only where a cheap one can't do the job. |
| NFR-4 | Survives a worker restart mid-run, including while waiting for the expert. |
| NFR-5 | CI passes (Ruff, schema check, Pyright, pytest); no real network calls in tests. |

## 3. Acceptance criteria (from intent "Done means")

Tested live with Ali, on Youssef's laptop.

| ID | Check | Proved by |
|---|---|---|
| AC-1 | A full run finishes on a site **Ali picks**, not one we prepared | Demo + an integration test on a fixed recorded site |
| AC-2 | At least one agent escalates to Ali live, and his answer is used | Demo + the escalation resume test (§5.4) |
| AC-3 | Ali edits one result and the dependent steps rerun | Demo + the edit propagation test (§5.5) |
| AC-4 | Every claim on the summary cards links to a real source | The evidence-completeness test (every output fact has evidence) + demo |

## 4. Scope ranking (proposal: what gets cut first if we fall behind)

Intent constraint: *any part can be simplified if we fall behind.* This ranking decides the
order in advance.

| Level | Items |
|---|---|
| **Must** (needed for AC-1–AC-4) | All six agents with web search, Google Places and OSM. Evidence on every fact. Live escalation with resume. Edit and rerun. Step-level progress. Summary cards with sources. |
| **Should** | The trained escalation scorer (fallback: the rule in FR-7). Recommended business types. The Documents tab. |
| **Could** | Community and social sources (Facebook, Instagram, X). Token streaming inside steps. Polish on the full report view. |

Cut from the bottom up: Could → Should. Never cut a Must.

---

## 5. Phase design

### 5.1 Placement

| Part | Module |
|---|---|
| Graph, agents, prompts | `app/phases/research/` (`interface.py` stays the only entry point) |
| Tools: Places, OSM, web search, elevation, (later) social | `app/shared/tools/`, since later phases reuse them |
| Escalation interrupt helper, scorer client | `app/shared/hitl/` |
| Model routing and caching | `app/shared/models/` |
| Waiting for the expert, rerun on edit | `app/orchestrator/` |
| New routes | `app/api/routes/` |

### 5.2 Contracts: gp-schemas changes

| Schema file | Change |
|---|---|
| `concept_input` | Add `business_types: string[]` (optional, may be empty). |
| `progress_event` | Rename the fields to the decided names: `progress_phase`, `progress_status`, `progress_step`, `progress_percent`. Add `progress_agent` (which agent) and an optional `escalation_id` while waiting. |
| `evidence` **(new, proposal)** | `{ fact_type: computable \| retrieved \| expert, source: { kind: url \| api \| function \| escalation, ref, title? }, retrieved_at }`. |
| `escalation` **(new)** | `escalation_id, concept_id, phase, agent, question, context (facts with evidence), choices[2–4], allow_free_text, scorer_score?, status: open \| answered \| timed_out, answer?, created_at, answered_at?` |
| `research_output` **(new)** | The six output fields in §5.7; every fact inside them embeds an `evidence` object. |

The backend heartbeat also renames its fields: `phase_step_agent`, `phase_percent`.

### 5.3 API (singular `/concept` for one concept)

| Route | Purpose | Status |
|---|---|---|
| `POST /concept` | Start a run (now accepts `business_types`) | exists, small change |
| `WS /ws/concept/{concept_id}` | Progress events, including escalation events | exists, renamed fields |
| `GET /concept/{concept_id}/phase/research` | Latest research result (all fields, with evidence) | new |
| `GET /concept/{concept_id}/escalation/{escalation_id}` | The escalation question, context and choices | new |
| `POST /concept/{concept_id}/escalation/{escalation_id}/answer` | The expert's answer → Temporal signal | new |
| `PATCH /concept/{concept_id}/phase/research/field/{field_path}` | Edit a field → new version + rerun of its dependents | new |

### 5.4 Escalation, end to end

The rule is already decided: LangGraph pauses at a checkpoint and Temporal waits for the
expert's signal. The design:

1. The agent node calls `interrupt(payload)`. The graph stops and returns the interrupt.
2. `run_phase` (the activity) returns `{status: waiting_for_expert, escalation}` instead of
   a result. The escalation row is saved.
3. `ConceptWorkflow` sets `workflow_status = waiting_for_expert` and waits for the
   `expert_answer` signal with a timeout (see Q4).
4. The WebSocket shows the escalation, and the UI shows the question card.
5. Ali answers → `POST …/answer` → the workflow receives the signal → it runs a
   `resume_phase` activity, which calls the graph with `Command(resume=answer)` on the
   same thread (`thread_id = concept_id + ":research"`).
6. The graph continues from the paused node. The answer becomes an `expert` fact, with the
   escalation id as its source.

**Checkpointer (proposal):** a Postgres checkpointer on the Supabase database, so a paused
run survives a worker restart (NFR-4). The in-memory checkpointer loses the pause whenever
the worker restarts.

**Stored for later:** the question, context, answer and scorer features. They are retrieved
as memory in later runs and used as training data for the scorer.

### 5.5 Edit and rerun

Dependencies inside Phase 1:

```
site_analysis ─┐
market ────────┴─► gaps ─► segments, competitors ─► supervisor_review, recommended_business_types
```

| Field edited | Reruns |
|---|---|
| `site_analysis` or `market` | gaps → segments, competitors → supervisor |
| `gaps` | segments, competitors → supervisor |
| `segments` or `competitors` | supervisor |
| `supervisor_review` / `recommended_business_types` | nothing |

**How (proposal):** the edit saves a new version with the user's value (as an `expert` fact,
sourced to the user). The workflow then reruns the graph, passing the already-saved fields
in its state. Nodes whose inputs' hashes didn't change return their saved value without
running. Every rerun saves a new version.

### 5.6 Failure handling (shared by all agents)

| External call | Timeout | Retry on | Final failure → |
|---|---|---|---|
| LLM | 60 s | timeout, 429, 5xx (3 attempts, backoff) | the step fails → Temporal retries the activity |
| Google Places | 10 s | timeout, 429, 5xx | the fact becomes human-only → escalate |
| OSM (Overpass) | 25 s | timeout, 429, 5xx | escalate, or fall back to Places for roads where possible |
| Web search | 15 s | timeout, 429, 5xx | escalate |

- **Idempotent saves:** a phase result is keyed by (concept, phase, version); the unique
  constraint already exists in `app/shared/db.py`.
- **Parallel branches:** one branch failing retries only that branch inside the graph. If it
  still fails, it escalates rather than failing the whole phase.
- **Rate limits:** parallel calls to the same provider are throttled in `app/shared/tools/`.

### 5.7 Research output fields

| Field | Produced by | Read by (in Phase 1) | Read by (later phases) |
|---|---|---|---|
| `site_analysis` | Site analysis | gaps | brand_design, investment |
| `market` | Market research | gaps | brand_design, investment |
| `gaps` | Gap analysis | segments, competitors | brand_design |
| `segments` | Segments | supervisor | brand_design, visuals |
| `competitors` | Competitors | supervisor | brand_design, investment |
| `supervisor_review` + `recommended_business_types` | Supervisor | — | brand_design |

Research `READS` stays `()`: it reads only the concept input.

**Graph state:** the parallel branches (Site + Market, Segments + Competitors) each write
their own key, so they don't collide. The keys that several nodes append to (`escalations`,
`supervisor_feedback`) use a list reducer (`Annotated[list[...], operator.add]`).

### 5.8 Progress steps

| Agent | `progress_agent` | Example `progress_step` values |
|---|---|---|
| Site analysis | `site_analysis` | `fetching_roads`, `computing_sun_path`, `summarizing` |
| Market research | `market_research` | `searching`, `reading_sources`, `summarizing` |
| Gap analysis | `gap_analysis` | `comparing`, `checking_evidence` |
| Segments | `segments` | `searching`, `matching_to_site` |
| Competitors | `competitors` | `searching_places`, `classifying` |
| Supervisor | `supervisor` | `reviewing`, `rerunning:<agent>`, `recommending` |

Every step change heartbeats. Token streaming is a **Could** (§4).

---

## 6. Agent designs (drafts: each owner reviews and changes theirs)

### 6.1 Site analysis · Owner: TBD

| Fact | Type | Produced by | Source |
|---|---|---|---|
| Nearby roads, road types, access points | retrieved | OSM Overpass tool | Overpass query |
| Distance to main roads and landmarks | computable | geometry function on OSM data | function name |
| Sun path / orientation through the year | computable | sun-position function (e.g. `astral`/`pvlib`) | function name |
| Terrain / elevation | retrieved | elevation API (**which one: Q6**) | API + query |
| Zoning / building regulations | human-only | escalation | escalation id |
| Short site summary | LLM over the facts above | cheap model | the facts it cites |

- **Pattern:** fixed workflow (row 2). The steps are known, and most of them are plain
  functions. One LLM node writes the summary from the facts.
- **Escalation:** zoning is always escalated in v1 (no reliable source). Also escalates if
  OSM returns nothing around the pin.
- **Model:** cheap tier, summary only. OSM and elevation results are cached by rounded
  lat/lng.
- **Tests:** unit tests for the distance and sun-path functions with known answers; a
  recorded Overpass response; "empty OSM → escalates".

### 6.2 Market research · Owner: TBD

| Fact | Type | Produced by | Source |
|---|---|---|---|
| Market trends for the area and the business types | retrieved | web search tool | URLs |
| Relevance to Egypt Vision 2030 and the tourism strategy | retrieved | web search (official sources first) | URLs |
| Local demand signals | retrieved (**Could**) | community/social tool | post URLs |
| Market summary | LLM over the facts above | strong model | the facts it cites |

- **Pattern:** single tool-calling agent (row 4). Which searches to run depends on what
  earlier searches return. **Stop rule:** at most 6 tool calls; at the limit, return what it
  has, with gaps marked, and escalate if a business type has no sources.
- **Escalation:** sources conflict on a key fact, or a business type has no sources.
- **Model:** cheap tier for writing search queries; strong tier for the final synthesis,
  because it has to reconcile several sources.
- **Tests:** recorded search responses; "conflicting sources → escalates"; every summary
  sentence cites a fact.

### 6.3 Gap analysis · Owner: TBD

| Fact | Type | Produced by | Source |
|---|---|---|---|
| Unmet demand: what the area lacks relative to its site and market | LLM reasoning over `site_analysis` + `market` facts | strong model | the facts it cites (must cite ≥ 1 each) |
| Strategy fit (Vision 2030 / tourism) for each gap | LLM over retrieved facts | strong model | cited facts |

- **Pattern:** fixed workflow with one structured-output LLM node, then a deterministic
  check that every gap cites evidence (row 2). Not a critic loop, because the Supervisor
  already reviews.
- **Escalation:** a gap with no supporting fact is dropped, or escalated if it's the only gap
  for a business type the user asked for.
- **Model:** strong tier: this is the main reasoning step.
- **Tests:** "a gap without evidence is rejected"; a fixed input gives a stable structure.

### 6.4 Segments · Owner: TBD

| Fact | Type | Produced by | Source |
|---|---|---|---|
| Who lives, works or passes near the site | retrieved | web search, Places (nearby universities, offices, residential) | URLs / API |
| Population and demographic figures | retrieved, or **human-only** when no source exists | search → escalation | URL / escalation id |
| Segment ↔ gap match | LLM over the facts above | strong model | cited facts |
| Segment size or share | retrieved or expert **only**, never estimated | — | source |

- **Pattern:** single tool-calling agent (row 4), stop rule: at most 5 tool calls.
- **Escalation:** demographic figures with no source. In Egypt these are often missing, so
  this is the most likely live escalation for AC-2.
- **Note:** the current stub returns `"share": 0.4`. That's exactly the kind of estimated
  number FR-5 forbids; the real agent must replace it with a sourced value or an escalation.
- **Model:** cheap tier for search; strong tier for matching.
- **Tests:** "no demographic source → escalates"; "no share without evidence".

### 6.5 Competitors · Owner: TBD

| Fact | Type | Produced by | Source |
|---|---|---|---|
| Businesses within the search radius | retrieved | Google Places nearby search | Places API + query |
| Rating, price level, opening hours | retrieved | Places details | Places API |
| Search radius | computable | rule by area type (**value: Q7**) | function name |
| Category per business type | LLM classification over retrieved data | cheap model | the place ids |
| Competitive summary per business type | LLM over the facts above | cheap model | cited place ids |

- **Pattern:** fixed workflow (row 2): search → details → classify → summarize.
- **Escalation:** zero results for a requested business type (is it truly absent, or is the
  data missing?).
- **Model:** cheap tier throughout. Places results are cached by (lat/lng, radius, type).
- **Tests:** recorded Places responses; classification on fixed data; "zero results →
  escalates".

### 6.6 Supervisor · Owner: TBD

| Fact | Type | Produced by | Source |
|---|---|---|---|
| Review: coverage, contradictions, missing evidence | LLM + deterministic checks | strong model + functions | the fields reviewed |
| Recommended business types (with reasons) | LLM over all fields | strong model | cited facts |

- **Pattern:** supervisor (row 6). Deterministic checks run first: every fact has evidence,
  every requested business type is covered. Then an LLM review decides: finish, rerun one or
  more agents with feedback, or escalate.
- **Stop rule:** at most 2 rerun rounds; then it finishes and lists the open issues in
  `supervisor_review`. It also escalates when it can't resolve a contradiction.
- **Escalation:** contradictions between agents that it can't settle from the evidence.
- **Model:** strong tier, because it judges the other agents' work.
- **Tests:** "a fact without evidence triggers a rerun"; the stop rule at 2 rounds; recorded
  model outputs.

---

## 7. Open questions (Youssef decides)

| # | Question | Options | Recommendation |
|---|---|---|---|
| Q1 | Accept the `evidence` schema in §5.2? | as is / change fields | as is: it's what AC-4 needs |
| Q2 | Checkpointer for paused runs | Postgres on Supabase / in-memory | Postgres: an in-memory checkpointer fails NFR-4 |
| Q3 | Accept the scope ranking in §4? | as is / reorder | as is |
| Q4 | What happens when the expert doesn't answer in time | keep waiting / remind, then wait / continue with the fact marked "unconfirmed" | remind, then wait: live demos need the answer used (AC-2) |
| Q5 | Agent owners | assign one teammate per agent in §6 | decide at the sprint meeting |
| Q6 | Elevation data source | Open-Elevation / Google Elevation / skip terrain in v1 | Google Elevation: same key as Places |
| Q7 | Competitor search radius | fixed (e.g. 1 km) / by area type (urban vs desert road) | by area type, with values from Ali |
| Q8 | The progress rename touches gp-schemas, backend and frontend | do it in Sprint 2 first / later | first: every new event uses the new names |
