# Web search comparison: Tavily, Arabic queries and mixed strategy (v3)

Date: 2026-11-27 · Tool: Tavily · Compared with: [v1 baseline](2026-11-27_tavily_v1.md),
[v2](2026-11-27_tavily_v2.md)
Status: **v3 is the best result so far**. It's adopted as the direction, but its restricted
searches are unreliable and need fixing before the design is final.

## Summary

- **Arabic queries alone** (v1 settings, `queries_v2.json`) cut developer pages a lot (45% → 10%)
  but replaced them mostly with Facebook posts and unknown sites. Citable sources didn't rise.
- **The mixed strategy (v3)** returns **3× more citable sources per question** than v1 (3.1 vs
  1.0), mainly news (18% of results against 5%) and listing and booking sites. Big Egyptian
  sources now appear: Egypt Today, Daily News Egypt, Mubasher, SIS (Arabic), Aqarmap, Zawya, and
  a Knight Frank report.
- **The catch:** the two restricted searches come back empty about half the time, and the same
  query flips between 0 and 6 results from one run to the next. That looks like an API
  reliability problem, not missing content.

## What was run

| Run | Settings | Queries | Calls |
|---|---|---|---|
| Arabic open | v1 (general, basic, country egypt, 10 results) | `queries_v2.json` (Arabic) | 12 × 2 = 24 |
| v3 mixed | 3 searches per question: Arabic restricted to `ar`+`both` citable domains, English restricted to `en`+`both` citable domains, English open search | v1 + v2 | 12 × 3 × 2 = 72 |

## Output: all results by source type

| | v1 English | v2 prefer | Arabic open | **v3 mixed** |
|---|---|---|---|---|
| Citable per question (official + news + report) | 1.0 | 1.2 | 0.9 | **3.1** |
| Results per question | 9.4 | 9.2 | 7.9 | 13.9 |
| Official | 4% | 3% | 4% | 4% |
| News | 5% | 8% | 7% | **18%** |
| Reports | 2% | 1% | 0% | 1% |
| Listing / booking | 15% | 15% | 15% | **32%** |
| Developer / broker | 45% | 35% | 10% | 23% |
| Social | 7% | 10% | **25%** | 5% |
| Paid report pages | 5% | 5% | 0% | 1% |
| Not in either list | 14% | 22% | **38%** | 16% |
| Time per question | 1.1 s | 2.1 s | 1.9 s | **8.3 s** |
| Credits per question | 1 | 1 | 1 | 3 |

## Output: per query

Citable results per question, then developer/broker, averaged over runs.

| Query | v1 English | Arabic open | v3 mixed |
|---|---|---|---|
| sokhna_q1 market division | 2.0 · 0.0 | 3.0 · 0.0 | **6.5** · 0.0 |
| sokhna_q2 area projects | 0.9 · 5.9 | 0.0 · 1.5 | **4.0** · 5.0 |
| sokhna_q3 prices | 0.0 · 4.0 | 0.0 · 1.0 | 0.0 · 0.5 (but 14 listing results) |
| sokhna_q4 demand | 1.0 · 1.0 | 1.0 · 0.0 | **2.0** · 1.0 |
| sokhna_q5 supply | 0.0 · 0.0 | 0.0 · 0.0 | **3.5** · 0.0 |
| sokhna_q6 strategy fit | 4.8 · 0.0 | 4.0 · 0.0 | **7.0** · 0.0 |
| obour_q1 market division | 0.1 · 7.0 | 1.0 · 1.0 | 0.5 · 6.0 |
| obour_q2 area projects | 0.4 · 7.9 | 0.0 · 1.0 | **2.0** · 5.5 |
| obour_q3 prices | 0.0 · 6.6 | 0.5 · 2.0 | **2.5** · 6.0 |
| obour_q4 demand | 0.0 · 8.9 | 0.0 · 0.5 | **2.5** · 8.0 |
| obour_q5 supply | 0.9 · 5.8 | 0.0 · 2.0 | **2.5** · 5.0 |
| obour_q6 strategy fit | 1.9 · 4.4 | 1.0 · 0.0 | **4.5** · 2.0 |

v3 improves or matches v1 on 11 of 12 queries. Ain Sokhna gains the most. New Obour City
gains less: citable sources rise, but developer pages stay high, because famous sources say
little about a new city.

## Weaknesses

1. **Restricted searches are flaky.** The Arabic restricted search was empty in 11 of 24 runs, and
   the English one in 13 of 24. The same query often flips between 0 and 6 results across two
   runs (e.g. `sokhna_q4`: Arabic 4 → 0, English 6 → 0). With a long domain list, Tavily seems
   to time out or drop results without returning an error. This is the main thing to fix.
2. **Restricted searches never return more than 6 results**, even with `max_results: 10`.
3. **Arabic open search brings social noise.** 25% of results were Facebook or Instagram posts,
   and 38% were sites not in our lists (many small Arabic broker sites).
4. **Slow and more expensive.** 8.3 s and 3 credits per question. For the Market agent's
   6-call limit, that means only 2 questions per run, so the limit or the design must change.
5. **The `unique_from_*` columns look wrong.** Each search's "unique" count always equals its
   result count, which would mean the three searches never return the same link. Bayut and
   Property Finder appear in both open and restricted results, so some overlap is expected.
   `score.py` should be checked.
6. **The zip of v3 run files was broken:** every file held only the text "1". These numbers come
   from `scores.csv` only.

## What was learned

- **Arabic is needed, but only when restricted to known sites.** Open Arabic search drifts to
  social posts; restricted Arabic search brings Arabic news and official pages.
- **The open search is still needed.** For New Obour City it carries most of the useful price
  and mall information, from small sites that no list covers.
- **Source lists work as the control.** Restricting to them is what raised citable sources, not
  the query language alone.

## Next

1. **Fix the flaky restricted searches** (one change: retry an empty restricted search once).
   If that doesn't help, split each domain list into smaller groups (e.g. news, official,
   listings) and search them separately.
2. **Check the `unique_from_*` calculation** in `score.py`.
3. **Re-zip the v3 run files** so the raw results can be checked.
4. **Add the new Arabic sites to the source lists**: bayut, aqarmap and nawy are already there;
   new ones include tamliek.com, newstart-eg.com, obourguide.com, mudirapp.com, mhuc.gov.eg,
   newcities.gov.eg, tda.gov.eg and aleqaria.com.eg.
5. **Decide the call budget** for the Market agent in spec 6.2: either raise the limit or use
   the 3-search mix only for the question groups that gained most (market division, supply,
   strategy fit).
