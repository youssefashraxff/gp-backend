# X2 web search: tool decision for the Market research agent

Date: 2026-11-28 · Plan task: X2 (Market research experiment), tool part
**Decision: Serper (Google Search API), with 3 searches per question.**

## Question

Which web search tool and search design gives the Market research agent the most **relevant,
citable, dated** sources for Egyptian sites, reliably and cheaply?

## Method

- 12 fixed queries: 6 question groups (market division, area projects, prices, demand, supply,
  strategy fit) for two of Ali's past sites, Ain Sokhna (tourist coast) and New Obour City (new
  city). English (`queries.json`) and Arabic (`queries_v2.json`) versions.
- No LLM: the same queries go straight to each tool, and the raw responses are saved in `runs/`.
- `score.py` labels every result with the two source lists (`egypt_sources.csv`, 134 sites;
  `international_sources.csv`, 83 sites) and checks it in code:
  - **relevant:** title, snippet or URL names the place **and** a keyword of the question's topic
  - **citable:** official, news, report or data source
  - **fresh:** dated within 24 months
- One setting changed per version. Per-run reports are in this folder.

## Results

"Relevant citable" = relevant results from citable sources, per question.

| Version | What it does | Calls / q | Relevant citable / q | Developer | Social | Fresh | Empty restricted searches | Seconds / q |
|---|---|---|---|---|---|---|---|---|
| Tavily v1 | English, open search | 1 | 2.0 | 48% | 7% | 0% | n/a | 1.1 |
| Tavily v2 | v1 + "prefer" citable domains | 1 | 1.8 | 46% | 10% | 0% | n/a | 2.1 |
| Tavily, Arabic | Arabic queries, open search | 1 | 2.4 | 26% | 25% | 0% | n/a | 1.9 |
| Tavily v3 | Arabic restricted + English restricted + English open | 3 | 5.6 | 26% | 5% | 0% | 24 / 48 | 8.3 |
| Tavily v4 | v3 with shorter domain lists | 3 | 4.2 | 31% | 8% | 0% | 26 / 48 | 7.7 |
| Serper v1 | English open + Arabic open | 2 | 4.4 | 30% | 22% | 24% | n/a | 2.9 |
| **Serper v2** | v3 design using Google `site:` operators | 3 | **13.4** | 15% | 4% | 46% | **0 / 48** | 5.4 |
| Serper v3 | v2 + site lists per question group | 3 | 14.0 | 14% | 4% | 35% | 1 / 24 | 6.6 |
| Serper v4 | v3 + date filter (24 months) on site searches | 3 | 12.2 | 14% | 4% | 78% | 1 / 24 | 7.6 |
| **Serper v5** | v3 + date filter only for market, projects, prices, demand | 3 | 12.2 | 14% | 3% | 61% | 1 / 24 | 6.5 |

## What we learned

1. **Restricting to known, trusted sites is what brings citable sources.** Open search, in any
   language or tool, returns mostly developer/broker sales pages (Tavily) or Facebook posts
   (Arabic open search).
2. **Tavily's restricted search is unreliable.** About half the restricted searches came back
   empty with no error. Empty ones stop at about 3 seconds (median 3.01 s), so this looks like a
   server-side time limit. Shorter domain lists made it worse, not better.
3. **Serper does the same restriction reliably through Google `site:`**, at **2–3× the relevant
   citable results of Tavily v3**, with almost no empty searches, and it returns dates (Tavily
   returned none).
4. **Arabic matters, but only restricted.** Restricted Arabic searches bring Youm7, Al-Masry
   Al-Youm, Masrawy, Al Mal, Al Borsa and SIS; open Arabic search brings social posts.
5. **The open search is still needed:** it finds local sources outside the lists, especially for
   a new city like New Obour.
6. **Google results change over time.** The same query 15 minutes apart shared only 0–5 of 10
   links. Runs seconds apart were identical, most likely Serper's cache. So Serper v3/v4/v5
   (12–14) are within run-to-run noise of each other; the gap to Tavily (2–6) is not.

## Decision for spec 6.2

- **Tool:** Serper (`gl: eg`; `hl: en` / `hl: ar`; `num: 10`).
- **Per question, 3 searches, merged and de-duplicated:**
  1. English query, open
  2. Arabic query restricted to the Arabic site group (10 sites, `site:` operators)
  3. English query restricted to the English site group (10 sites)
- **Site groups by question type:** news (market, projects, demand), prices (listing sites),
  supply (booking and hospitality), strategy fit (official sites). Kept in `settings/serper_v5.json`.
- **Date filter (last 24 months)** on the site searches for market, projects, prices and demand;
  off for supply and strategy fit, where older pages (hotel counts, national plans) stay valid.
  Chosen on principle, since the numbers can't separate v3/v4/v5.
- **Evidence rule:** every result keeps its URL and date; old or undated results are flagged for
  the agent, never used silently.

## Limits to keep in mind

- Code-based relevance is rough: naming the place and topic doesn't prove a result answers the
  question. The model's reading in X2 is the real check.
- Strategy fit is the weakest group in every version (about 5–7 relevant citable per question):
  official sites rarely name the specific place.
- 3 calls per question uses half of the current 6-call limit for one question; the call budget
  is a design point for spec 6.2.
- Because results change, tests must use recorded responses (A3), never live searches.
- Cost: well within Serper's free 2,500 queries for all experiments so far.

## Next

1. Update spec 6.2 with this decision.
2. Build Serper into the shared tool client (A3) with recorded responses.
3. Continue X2 with the model in the loop: the prompt writes the queries, and the search layer
   above runs them.
