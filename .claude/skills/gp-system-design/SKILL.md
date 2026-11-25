---
name: gp-system-design
description: The method for designing a new backend part of the Concept Development GP (an agent, a phase, a tool or data source, an escalation point, an API route or a stored field), from intent to a reviewed design section in spec.md. Use when writing or reviewing the design part of a spec.md or plan.md, or when someone asks "how should we build X". Works together with gp-architecture, which holds the fixed rules.
---

# GP system design

`gp-architecture` says **what is already decided**. This skill says **how to design
something new** inside those rules. Run the steps in order. Each one produces a section of
the design, and together they make the design section of `spec.md` (template at the end).

**Golden rule:** the simplest design that meets the intent wins. Every extra agent, loop or
service has to earn its place against the intent's "Done means" checks. If two options both
meet them, pick the one a teammate can understand in 10 minutes.

**Decisions stay with Youssef.** When a step has real options, write 2–3 of them, each with
its trade-off and a recommendation. Don't silently pick one. Any rule from gp-architecture
the design bends goes under **Open questions**.

---

## Step 1: Classify every piece of information

This is the project's core claim: the system **never guesses**. Before choosing any agent or
tool, list every fact the part needs or produces and give each one exactly one type:

| Type | Meaning | Who produces it | Phase 1 examples |
|---|---|---|---|
| **Computable** | Derivable by code from known inputs | a deterministic function (no LLM) | sun path, distances, catchment radius, road access from OSM geometry |
| **Retrievable** | Exists somewhere you can query | a tool call with a stored source | nearby competitors (Places), market facts (web search), community sentiment (social groups) |
| **Human-only** | Only the expert knows it, or the sources disagree or are missing | an escalation to the expert | real local rent levels, an unwritten local regulation, a judgement call between conflicting sources |

**Rules:**
- An LLM may **reason over, summarize and connect** facts. It never *invents* a computable,
  retrievable or human-only fact. A number an LLM "estimates" is a bug.
- If something is computable, write the function. Don't ask an LLM.
- If retrieval fails or the sources conflict, the fact becomes **human-only for this run**
  (it escalates). It never falls back to a guess.

Output: a table `| Fact | Type | Produced by | Source |`.

## Step 2: Find its home

Use this decision path (homes and import rules are in gp-architecture §1–§3):

```
Is it about receiving a request or streaming to the browser?   → app/api/
Is it about order between phases, waiting, retries, approval?  → app/orchestrator/ (Temporal)
Is it the work of one phase?                                    → app/phases/<phase>/ (LangGraph)
Will two or more phases use it (tool, model routing, HITL)?     → app/shared/
Does data cross the API, the WebSocket or a saved result?       → a schema in gp-schemas first
```

**Temporal determinism:** workflow code (`workflows.py`) must be deterministic. No I/O, no
network calls, no `datetime.now()`, no randomness. Anything like that belongs in an
**activity**. This is the most common way to break Temporal.

## Step 3: Choose the agent pattern

Pick from this menu, **simplest first**. Move down a row only when the row above can't meet
the intent.

| # | Pattern | Use when | LangGraph shape |
|---|---|---|---|
| 1 | **Plain function** | the work is computable | no LLM, a normal node or a tool |
| 2 | **Fixed workflow** | the steps are known in advance | nodes + edges, no agent decides the order |
| 3 | **Parallel fan-out / fan-in** | independent analyses on the same input | parallel edges or `Send`, then a join node |
| 4 | **Single tool-calling agent** | the steps depend on what the tools return | an agent node + tool node loop, **with a max-iterations limit** |
| 5 | **Critic / reflection loop** | output quality must be checked against criteria | producer → critic → back (max N rounds) |
| 6 | **Supervisor** | several agents, and someone must decide reruns and when to stop | supervisor node routes to workers with `Command` / conditional edges |

**Phase 1 (decided flow):** Site + Market (pattern 3) → Gaps → Segments + Competitors
(pattern 3) → Supervisor (pattern 6). Inside each box, the person assigned to that agent
chooses its pattern from this menu and writes down why.

**Every loop needs a stop rule:** a max-iterations count, and what happens when it's hit
(escalate or return partial work, **never** loop until success).

Output: the chosen pattern per node, plus *one line on why the row above wasn't enough*.

## Step 4: Design the state and the contracts

- **Graph state** (`TypedDict`): only what the nodes inside this phase pass to each other.
  Keys that **parallel branches write to need a reducer**
  (`Annotated[list[X], operator.add]`). Without one, LangGraph raises an error when two
  branches update the same key.
- **Phase output:** the fields saved in the `PhaseResult`. Name each output field, give its
  type, and say **which later phase reads it** (for that phase's `READS`).
- **Every claim carries its evidence.** Each output fact keeps where it came from: its type
  (computable, retrieved or expert), its source (URL, API plus query, function name, or
  escalation id) and when it was retrieved. This is what lets the UI link every claim on a
  card to its source. Define this shape once in gp-schemas and reuse it everywhere.
- **Schemas first:** any new or changed field → a gp-schemas change → regenerated types. The
  spec names the schema file.

## Step 5: Place the escalation points

For each **human-only** fact from Step 1, design the escalation:

1. **Where:** which node pauses. It uses LangGraph's `interrupt()` with a checkpointer, so
   the run resumes from that node and **never restarts the phase**.
2. **Who decides to ask:** the escalation scorer (a small supervised classifier) gives a
   score from the node's context; above the threshold, it escalates. Until the scorer is
   trained, the rule from Step 1 decides (missing or conflicting sources → escalate).
3. **What the expert sees:** the question, the context (what the agent found, with
   sources), **2–4 suggested answers to choose from**, a free-text option, and why it is
   asking. An expert should be able to answer in under a minute.
4. **How it resumes:** the API receives the answer → Temporal signal → resume with
   `Command(resume=answer)`. Define a timeout and what happens when it's hit (keep waiting,
   remind, or continue with the fact marked "unconfirmed").
5. **What is kept:** the question, the answer, the context and the scorer's features are
   stored. Expert answers are **retrieved later as memory, not trained into a model**. The
   (context, escalated?, answer) records are also the training data for the scorer.

## Step 6: Choose the model and the cost per LLM node

For each node that calls an LLM: which tier (cheap or strong) and why, the input size
expected, and whether its result can be **cached** (retrieval results and expensive calls
keyed by input hash). LangGraph has no token budgets, so budgets are enforced in the model
layer in `app/shared/`. If a node uses the strong tier, write the one thing the cheap tier
can't do there.

## Step 7: Design for failure

Temporal retries activities, so:

- **Idempotent activities:** running one twice must not create duplicates. Saving a phase
  result uses its (concept, phase, version) as the key; the database's unique constraint
  catches a second insert.
- **For every external call** (search, Places, OSM, social, LLM): its timeout, what counts
  as retryable (timeouts, 429, 5xx) and what doesn't (bad input, 4xx), and what the user
  sees if it finally fails.
- **Rate limits:** batch or throttle the parallel calls to one provider.
- **Long activities heartbeat**, so Temporal can tell slow apart from dead.
- **Partial success:** decide whether one failed branch fails the phase, retries just that
  branch, or escalates. Write it down; don't leave it to the default.

## Step 8: Progress and streaming

List the progress events the part sends, using the names from gp-architecture §6:
- the heartbeat carries `phase_step_agent` and `phase_percent`;
- `ProgressEvent` carries `progress_phase`, `progress_status`, `progress_step` and
  `progress_percent`.

Say which node sends which step, and whether it streams tokens. The user should never see
more than ~5 seconds without a visible change.

## Step 9: Edit propagation

- Which earlier fields this part reads → its `READS` (also recorded at run time).
- Which of its outputs other parts read → they become stale when it changes.
- When a user edits one of its outputs: which nodes rerun, and which stay as they were.
  Unchanged hashes rerun nothing.

## Step 10: Plan the tests and how it is evaluated

- **Computable nodes:** plain unit tests with known answers.
- **LLM nodes and tools:** tests with fake models and recorded tool responses. No real
  network in CI.
- **Temporal:** the workflow tested with the fakes in `tests/temporal_fakes.py`.
- **Escalation:** one test where the information is missing → escalates → resumes with the
  answer.
- **Evaluation:** which metric from the chosen papers this part is scored on, measured
  against brother Ali's past data (the escalation dataset) where it applies.
- Map each intent "Done means" check to at least one test or demo step.

---

## Design section template (paste into spec.md)

```markdown
## Design: <part name>

### Information (Step 1)
| Fact | Type | Produced by | Source |

### Placement (Step 2)
<module path(s)> — <one line why>

### Pattern (Step 3)
<pattern per node> — why the simpler row wasn't enough. Stop rule: <max N → what>.

### State and contracts (Step 4)
Graph state keys (+ reducers) · output fields (type, read by) · gp-schemas file(s)

### Escalation points (Step 5)
| Node | Trigger | Question + choices | Timeout behaviour |

### Models and cost (Step 6)
| Node | Tier | Why | Cached? |

### Failure handling (Step 7)
| External call | Timeout | Retry on | Final failure → user sees |

### Progress (Step 8)
| Node | phase_step_agent | Streams tokens? |

### Edit propagation (Step 9)
READS: ... · Read by: ... · Rerun on edit: ...

### Tests and evaluation (Step 10)
| Check from intent | Test / demo |

### Options considered
| Option | Trade-off | Chosen? |

### Open questions
- <rule bent or decision Youssef must make>
```

## Review checklist

- [ ] Every fact has exactly one type; no LLM produces a number or fact on its own
- [ ] The simplest pattern was chosen, and each step up the menu is justified
- [ ] Every loop has a max and a defined behaviour at the max
- [ ] Parallel state keys have reducers
- [ ] Every output fact carries its evidence (type, source, time)
- [ ] Every human-only fact has an escalation point, with choices and a timeout
- [ ] No I/O in workflow code; activities are idempotent
- [ ] Every external call has a timeout, retry rules and a user-facing failure
- [ ] Progress names follow gp-architecture §6
- [ ] `READS` is listed, and what reruns on an edit is defined
- [ ] Each intent "Done means" check maps to a test or demo step
- [ ] Options are written down with trade-offs; decisions are left to Youssef under Open questions
