# Intent: Phase 1 — Research

Status: proposed (merging this PR = accepted) · Owner: Youssef · Date: 2026-11-25

## Problem
Experts like Ali, and non-expert users after them, want precise, fast output with less effort.
Today that means moving between platforms and re-giving prompts and context every time.

## Users
- Experts like Ali: they check the output and answer escalations.
- Non-expert users who just want the result.
- We test with Ali.

## What it must do
- **Input:** a pin on a map, plus optionally the business type(s) the user is considering.
- **Research:** Site analysis + Market research → Gap analysis → Segments + Competitors,
  reviewed by a supervisor that can rerun steps.
- **Data sources:** web search API, Google Maps/Places, OpenStreetMap,
  community groups and social platforms (Facebook, Instagram, X).
- **Output:** findings from each step, plus business types the research recommends
  (alongside any the user entered).
- **Streaming:** steps stream live in the chat, for engagement and a feeling of speed.
- **Presentation:** precise, relatable, dependable output in a user-friendly way:
  summary cards in the chat, the full report opens in the chat, every source is clickable
  (Sources tab), and the chat's input/output docs are in the Documents tab.
- **Human-in-the-loop:**
  - Any agent escalates to the expert mid-task when it lacks grounded information, instead of guessing.
  - A trained escalation scorer decides when to escalate.
  - The user can edit a result in the UI and rerun whatever depends on it.

## Out of scope
- Phases 2–4 (Brand & Design, Visuals, Investment).
- Field-survey data input (deferred to a later version).

## Constraints
- Ready by Seminar 2 (week of 13 Dec 2026).
- Team capacity: about 8–12 hours per person per week.
- Fixed stack: Angular, FastAPI, Supabase, Temporal, LangGraph.
- Any part can be simplified if we fall behind.

## Done means
- Youssef takes the laptop to Ali and they run it live together.
- Pass if:
  - A full run finishes on a site Ali picks, not one we prepared.
  - At least one agent escalates to Ali live, and his answer is used.
  - Ali edits one result, and the dependent steps rerun.
  - Every claim on the summary cards links to a real source.
