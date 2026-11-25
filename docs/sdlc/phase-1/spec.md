# Spec: Phase 1 — Research

Status: **draft** (merging this PR = accepted) · Owner: Youssef · Date: 2026-11-25
Reads: [`intent.md`](intent.md) · Follows: `.claude/skills/gp-system-design`

How to read this file:
- **Sections 1–4:** *what* we build and how we know it's done.
- **Section 5:** the design of the whole phase. **Read 5.9 first** if you own an agent: it
  says how the agents share state and how the Supervisor's review loop works.
- **Section 6:** the design of each agent. Each agent section is a **draft for its owner to
  review and change**: the owner decides the agent's internal pattern, model and cost.
- **Section 7:** the decisions made on the open questions.

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
| FR-2 | **Run:** `POST /concept` starts the run. The six agents run in the order in section 1, inside one LangGraph per phase. |
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
| NFR-2 | Every external call has a timeout, retry rules and a message the user sees when it fails (section 5.6). |
| NFR-3 | Each LLM node states its model tier; strong models only where a cheap one can't do the job. |
| NFR-4 | Survives a worker restart mid-run, including while waiting for the expert. |
| NFR-5 | CI passes (Ruff, schema check, Pyright, pytest); no real network calls in tests. |

## 3. Acceptance criteria (from intent "Done means")

Tested live with Ali, on Youssef's laptop.

| ID | Check | Proved by |
|---|---|---|
| AC-1 | A full run finishes on a site **Ali picks**, not one we prepared | Demo + an integration test on a fixed recorded site |
| AC-2 | At least one agent escalates to Ali live, and his answer is used | Demo + the escalation resume test (section 5.4) |
| AC-3 | Ali edits one result and the dependent steps rerun | Demo + the edit propagation test (section 5.5) |
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
| `evidence` **(new)** | `{ fact_type: computable \| retrieved \| expert, source: { kind: url \| api \| function \| escalation, ref, title? }, retrieved_at }`. |
| `escalation` **(new)** | `escalation_id, concept_id, phase, agent, question, context (facts with evidence), choices[2–4], allow_free_text, scorer_score?, status: open \| reminded \| answered \| timed_out, answer?, created_at, reminded_at?, answered_at?` |
| `research_output` **(new)** | The six output fields in section 5.7; every fact inside them embeds an `evidence` object. |

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
   `expert_answer` signal. **Decided (Q4):** if there's no answer after the reminder time,
   it sends Ali a reminder and keeps waiting. If there's still no answer after the long
   limit, it **stops waiting**: the escalation is marked `timed_out`, the run stops with
   that status, and the WebSocket closes. Both times are workflow timers, so they cost
   nothing while waiting.
4. The WebSocket shows the escalation, and the UI shows the question card.
5. Ali answers → `POST …/answer` → the workflow receives the signal → it runs a
   `resume_phase` activity, which calls the graph with `Command(resume=answer)` on the
   same thread (`thread_id = concept_id + ":research"`).
6. The graph continues from the paused node. The answer becomes an `expert` fact, with the
   escalation id as its source.

**Checkpointer (decided, Q2):** a Postgres checkpointer on the Supabase database, so a
paused run survives a worker restart (NFR-4).

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

Every step change heartbeats. Token streaming is a **Could** (section 4).

### 5.9 How the agents work together

**Shared state, not hand-offs.** Agents don't pass their output to the next agent like a
relay. Each agent reads the state keys it needs and returns **only its own key** (e.g. Gap
analysis returns `{"gaps": ...}`); LangGraph merges it into the shared state. The arrows in
section 1 show **order**, not who can see what. So the Supervisor reads the whole state:
`site_analysis`, `market`, `gaps`, `segments` and `competitors`, not just the last two agents.

**The Supervisor reviews once, at the end.** It doesn't review after each agent, because:
- the most important problems are **contradictions between agents** (e.g. Gap says "no cafés
  nearby" but Competitors found 6), and those only show once every agent is done;
- each agent already runs its own code checks (below), so a per-agent LLM review would
  mostly find nothing and only add cost and waiting time.

**The review loop:**
1. The Supervisor writes its findings into `supervisor_feedback` as
   `{agent, issue, facts_involved}` items (list reducer, section 5.7).
2. It routes back to the flagged agent(s). Each agent reads the feedback addressed to it.
3. The flagged agent **and everything that depends on it** rerun, using the table in
   section 5.5. A parallel sibling whose inputs didn't change does **not** rerun (fixing
   Segments doesn't rerun Competitors; fixing Gaps reruns both).
4. The Supervisor reviews again. Stop rule: at most 2 rounds (section 6.6).

**Where the state lives.** The state is a normal Python `TypedDict` in memory. We don't
design SQL tables for it:
- the **Postgres checkpointer** (Q2) saves a snapshot after every node automatically. This
  is what lets a run pause for the expert and survive a restart;
- when the phase finishes, the final state is saved **once** as the versioned research
  result (section 5.6, idempotent saves). Edit and rerun (section 5.5) works on that.

**Where quality is checked (three layers):**

| Layer | Who | Checks | LLM cost |
|---|---|---|---|
| 1. Code checks | **every** agent, including Gap | output matches the schema; `check_evidence` (every fact has evidence) | none |
| 2. Careful sourcing | the data-gathering agents: Site, Market, Segments, Competitors | right tool use, stop rules, escalate when sources are missing or conflict | per agent design |
| 3. Cross-agent review | Supervisor | coverage, contradictions between agents, recommendations | strong model |

Site and Market need the most care inside the agent: everything else is built on them, and an
error caught only by the Supervisor means rerunning almost the whole chain. The reasoning
agent (Gap) skips extra LLM self-checks and relies on layer 1 plus the Supervisor.

**What the Supervisor can't catch:** it only sees the state, so it catches *inconsistency*
(agents disagree, a fact has no source). It can't tell whether a well-sourced fact is *true
in the real world*, e.g. a source that was read wrong but still cited. Accuracy against the
real world has to come from the agents that touch the sources (layer 2).

---

## 6. Agent designs (drafts: each owner reviews and changes theirs)

**How an agent section gets updated:**
1. The owner decides their agent's pattern (and model, tools, stop rule) using
   gp-system-design Part B, Step 3.
2. **Before writing the agent's code**, the owner opens a PR that updates *only their
   section* here. It changes `Status: draft` → `Status: decided` and records the pattern
   and why the simpler option wasn't enough.
3. Youssef reviews and merges it. The section is now the agent's contract.
4. The code PR links to the section. If the code needs a different design, update the
   section first (in that PR or a separate one), never just the code.

So the spec always says how each agent actually works.

**Guidance for owners (the drafts below follow it; your section can change it):**
- **Use a fixed workflow when you already know the steps.** It's cheaper, faster and easier
  to test. Use a tool-calling (ReAct) loop only when the next search depends on what the
  last one returned. Add a planning step only for long, open-ended tasks (in Phase 1, Market
  research comes closest).
- **Not every agent needs ReAct.** Site analysis and Competitors are fixed workflows; Gap
  analysis is one structured LLM call.
- **Every agent keeps the layer-1 code checks** (section 5.9) whatever pattern it uses.
- **Write down for your agent:** pattern (and why the simpler row wasn't enough), tools and
  the max number of tool calls, when it escalates, model tier, the exact state key it writes
  (its output schema), and the main tests.
- Output schemas come first (plan A1/A6): every agent and the Supervisor build against them,
  so once they're fixed, all owners can build in parallel.

### 6.1 Site analysis · Owner: TBD · Status: draft

| Fact | Type | Produced by | Source |
|---|---|---|---|
| Nearby roads, road types, access points | retrieved | OSM Overpass tool | Overpass query |
| Distance to main roads and landmarks | computable | geometry function on OSM data | function name |
| Sun path / orientation through the year | computable | sun-position function (e.g. `astral`/`pvlib`) | function name |
| Terrain / elevation | retrieved | Google Elevation API (Q6) | API + query |
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

### 6.2 Market research · Owner: TBD · Status: draft

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

### 6.3 Gap analysis · Owner: TBD · Status: draft

| Fact | Type | Produced by | Source |
|---|---|---|---|
| Unmet demand: what the area lacks relative to its site and market | LLM reasoning over `site_analysis` + `market` facts | strong model | the facts it cites (must cite ≥ 1 each) |
| Strategy fit (Vision 2030 / tourism) for each gap | LLM over retrieved facts | strong model | cited facts |

- **Pattern:** fixed workflow with one structured-output LLM node, then a deterministic
  check that every gap cites evidence (row 2). Not a critic loop, because the Supervisor
  already reviews.
- **Input and tools:** reads only `site_analysis` + `market` from the state; **no tools**.
  The research is already done, and this step is pure reasoning over checked facts. If it
  could search, it would bring in new facts that nobody checked, and the job split would
  blur. If the inputs aren't enough, that means an earlier agent missed something: it flags
  it in its output (the Supervisor routes it back) or escalates. It doesn't search itself.
- **Supply-side data (open, Q9):** a gap means *demand that nobody is serving*, but
  Competitors (the supply side) runs after Gap. Market research must bring enough supply
  information, or Gap would be guessing what's missing.
- **Escalation:** a gap with no supporting fact is dropped, or escalated if it's the only gap
  for a business type the user asked for.
- **Model:** strong tier: this is the main reasoning step.
- **Tests:** "a gap without evidence is rejected"; a fixed input gives a stable structure.

### 6.4 Segments · Owner: TBD · Status: draft

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

### 6.5 Competitors · Owner: TBD · Status: draft

| Fact | Type | Produced by | Source |
|---|---|---|---|
| Businesses within the search radius | retrieved | Google Places nearby search | Places API + query |
| Rating, price level, opening hours | retrieved | Places details | Places API |
| Search radius | computable | `competitor_radius(lat, lng)`, dynamic per location (**decided, Q7**) | function name |
| Category per business type | LLM classification over retrieved data | cheap model | the place ids |
| Competitive summary per business type | LLM over the facts above | cheap model | cited place ids |

- **Radius (decided: dynamic per location):** computed from how built-up the area around
  the pin is. Count the places/points of interest near the pin (OSM), then map that density
  to a radius: dense city streets get a small radius, while suburbs, new cities and desert
  roads get a larger one. The radius and its inputs are saved as a computable fact, so the
  user sees why it was chosen. (Proposal for the ranges, to tune with Ali: dense ≈ 0.5–1 km,
  suburban ≈ 2–3 km, desert road/highway ≈ 5–10 km.)
- **Pattern:** fixed workflow (row 2): radius → search → details → classify → summarize.
- **Escalation:** zero results for a requested business type (is it truly absent, or is the
  data missing?).
- **Model:** cheap tier throughout. Places results are cached by (lat/lng, radius, type).
- **Tests:** recorded Places responses; classification on fixed data; "zero results →
  escalates".

### 6.6 Supervisor · Owner: TBD · Status: draft

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
- **Option for the owner: debate for the judgment calls.** Inside the LLM review, a
  multi-agent debate (one agent argues for a conclusion, one attacks it, a judge decides,
  1–2 rounds) can catch weak reasoning a single reviewer misses.

  | Option | Trade-off | Recommendation |
  |---|---|---|
  | Single LLM reviewer | 1 strong call per round; stable outputs; easy to test | **Start here** |
  | Debate (proposer + critic + judge) | ~6 strong calls per round; outputs vary more; harder to test; agreement doesn't fix a missing source | Add **only** for contradictions and `recommended_business_types`, and only if test cases show the single reviewer missing things |

  The deterministic checks never go through debate. Comparing the two options on the same
  test cases is also a useful result for the report.

---

## 7. Decisions (were open questions)

| # | Question | Options | Decision |
|---|---|---|---|
| Q1 | Evidence schema in section 5.2 | — | **Decided: as proposed** |
| Q2 | Checkpointer for paused runs | — | **Decided: Postgres on Supabase** |
| Q3 | Scope ranking in section 4 | — | **Decided: as proposed** |
| Q4 | Expert doesn't answer in time | — | **Decided: remind, then stop waiting.** Defaults: reminder after **30 min**, stop after **24 h**, reminder in the app only for v1 (email/WhatsApp later), and a stopped run **can be restarted** from its saved checkpoint. Tune the times after the first test with Ali |
| Q5 | Agent owners | — | **Decided: assign at the Sprint 2 meeting**; each owner then updates their section 6 section (see section 6 process) |
| Q6 | Elevation data source | — | **Decided: Google Elevation API** (same key as Places) |
| Q7 | Competitor search radius | — | **Decided: dynamic per location** (density-based, section 6.5); start with the ranges in section 6.5 and tune them with Ali |
| Q8 | Progress rename | — | **Decided: first in Sprint 2.** gp-schemas done; backend and frontend follow with the submodule bump |
| Q9 | Supply-side data for Gap analysis (section 6.3) | (a) Market research collects basic supply info (what already exists in the area); (b) move a light Places count before Gap; (c) leave Gap demand-only and let the Supervisor check gaps against Competitors | **Open:** the Market and Gap owners propose one in their section PRs |
