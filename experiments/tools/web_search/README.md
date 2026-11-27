# Web search tool comparison

Before the Market research and Segments agents pick a web search tool, we compare the tools
**directly, with no LLM involved**. An LLM in the loop would mix two questions, "is the tool
good?" and "did the model use it well?", so here the same 12 fixed queries (6 per test site) go straight to each tool, and we save
and measure the raw results.

It is two steps:

| Step | Script | Calls an API? | Writes |
|---|---|---|---|
| 1. Collect | `compare.py` | yes | one new file per call in `runs/<tool>/<settings>/queries_<version>/` (never overwritten) |
| 2. Score | `score.py` | no | `scores.csv`, `summary.csv` (regenerated), `manual.csv` (rows only added) |

Collecting costs credits; scoring is free. So when a source list changes, just rescore.

## Run

Put `TAVILY_API_KEY=...` and `SERPER_API_KEY=...` in `.env` (never commit them), then:

```bash
# 1. collect: 12 queries x 2 runs (the default) = 24 calls
python -m experiments.tools.web_search.compare --tool tavily --settings v1 \
    --query all --notes "tavily v1 baseline"
python -m experiments.tools.web_search.compare --tool tavily --settings v1 \
    --query sokhna_q1 --runs 1        # one query, one call
python -m experiments.tools.web_search.compare --tool tavily --settings v1 \
    --queries v2 --notes "Arabic queries"   # the Arabic query version

# 2. score every run file under runs/ (all tools and settings)
python -m experiments.tools.web_search.score
```

Run files go in one folder per tool, settings version and query version, e.g.
`runs/tavily/v1/queries_v1/` (English) and `runs/tavily/v1/queries_v2/` (Arabic), so rounds
never mix. New file names also carry the query version (`…__tavily__v1__qv2__sokhna_q1__run1.json`).
Files from before query versions existed don't have the `q<version>` part; their
`query_version` is inside the file. `manual.csv` is keyed by file name (which starts
with a unique time), so moving files between folders doesn't lose what you wrote.

`compare.py` saves the full raw response, the cleaned-up results, the query, settings, run
number, time, `status` and `--notes`. If a call returns 0 results without an error it
retries once; if still empty the run is saved with status `empty`. A failed call is saved
with status `error` and the run goes on.

`score.py` prints the share of all results per type at the end, for a quick overview.

## Query versions

Pick one with `--queries` (default `v1`). Every version has the same 12 ids, sites and
groups, so a query can be compared across versions; `query_version` is saved in each run
file and is a column in `scores.csv` and `summary.csv`.

| Version | File | Language | What it is |
|---|---|---|---|
| `v1` | `queries.json` | English | the original 12 queries |
| `v2` | `queries_v2.json` | Arabic (`"language": "ar"`) | the same 12 queries in Arabic |

Never edit a version that has been run; add `queries_v3.json` with `"version": "v3"`
instead. Run files are saved as UTF-8, so Arabic stays readable in them.

## How a result is classified

The domain is lowercased, `www.` is stripped, and it is matched **by suffix** against
`egypt_sources.csv` and `international_sources.csv` (so `english.ahram.org.eg` matches
`ahram.org.eg`; whole labels only, so `notsavills.com` doesn't match `savills.com`). The
row's `source_type` decides the column. Then:

- an unlisted domain ending in `.eg` is Egyptian, with type `unlisted_eg`;
- type `ignore` (e.g. `tavily.com`) is dropped from **every** count, including `n_results`
  and `top3_urls`.

To add a source, add a row to one of the two CSVs and rerun `score.py`.

## scores.csv (one row per run file)

| Column | Meaning |
|---|---|
| `run_file` | The run file's name (the key into `manual.csv`) |
| `timestamp`, `tool`, `settings` | When, which tool, which settings version |
| `query_version`, `query_id`, `site`, `group`, `run` | Which query and repeat |
| `status` | `ok`, `empty` (0 results after a retry) or `error` |
| `n_results` | Results, not counting type `ignore` |
| `n_egyptian` | Results from a source with `egyptian=yes`, plus unlisted `.eg` domains |
| `n_official` | `official` + `intl_official` |
| `n_news` | `news` + `business_news` + `intl_news` |
| `n_report` | `consultancy_report` + `data_aggregator` |
| `n_listing` | `listing_portal` + `travel_booking` + `str_data` |
| `n_developer` | `developer_broker` |
| `n_social` | `social` |
| `n_paid_report` | `paid_report` |
| `n_unlisted` | In neither list (including unlisted `.eg` domains) |
| `n_with_date` | Results with a `published_date` |
| `unlisted_domains` | Those unlisted domains, so you can add them to a list |
| `top3_urls` | The first three URLs, joined by ` \| ` |
| `seconds`, `error` | How long the call took; the error if it failed |

For a **strategy** run (see below) the counts above are of the merged results, and each
search adds four columns at the end (empty for plain runs):

| Column | Meaning |
|---|---|
| `<search>_status` | `ok`, `empty` or `error` for that one call |
| `<search>_n_results` | Results of that call (type `ignore` dropped) |
| `<search>_n_citable` | Of those, how many are citable (types listed under Strategies) |
| `unique_from_<search>` | Merged results that **only** this search found: whether the call earns its credit |

Types without their own column (`lifestyle`, `academic`, `tourism_travel`, `maps_reviews`)
still count in `n_results`, and in `n_egyptian` when Egyptian.

## summary.csv (one row per tool + settings + query version + query)

`runs`, `ok`, `empty`, `errors`, then `avg_<column>` for each count above (averaged over
the runs that didn't error), `same_top3` (how many `ok` runs share the most common top-3
set; order doesn't matter) and `avg_seconds`. For strategy runs, each search also gets
`<search>_ok`, `<search>_empty`, `<search>_errors`, `avg_<search>_n_results` and
`avg_<search>_n_citable` (over the runs where that search didn't error) and
`avg_unique_from_<search>`.

## manual.csv: filling in `relevant` and `notes`

`score.py` adds a row for each new run file and never changes or deletes existing rows, so
what you write here survives every rescore. `notes` starts as the run's `--notes`.

For `relevant`, open the run file named in `run_file`, read the results, and write how many
of them actually help answer the query for that site (a number 0..`n_results`). Count a
result only if it is about the right place and gives usable information (a price, a
project, a number, a source we could cite). Judge one query across all tools before moving
to the next, so the standard stays the same.

## Settings versions

| Version | What changed |
|---|---|
| `tavily_v1` | `general`, `basic`, `country=egypt`, 10 results |
| `tavily_v2` | v1 + `include_domains` (105 domains of type official, news, report and listing types, copied from the two CSVs on 2026-11-27) with `include_domains_mode: prefer` |
| `tavily_v3` | **Strategy `mixed`** (Market research only): 3 searches per question, see below |
| `tavily_v4` | v3 with shorter restricted lists, regenerated after the CSVs dropped `both`: `ar_restricted` 30 domains (`language` `ar`), `en_restricted` 74 (`language` `en`) |
| `serper_v1` | **Strategy `mixed`**, 2 open searches: `en_open` (v1 English, `gl=eg`, `hl=en`, `num=10`) and `ar_open` (v2 Arabic, `gl=eg`, `hl=ar`, `num=10`). No `site:` operators, no domain filtering |

Add `settings/<tool>_v5.json` and run with `--settings v5`. Never edit a version that has
been run; old and new must stay comparable. Say what changed in `--notes`.

## Strategies (several searches per question)

A settings file with a `"strategy"` key runs several searches for each question and saves
them in **one** run file. This is for the Market research agent only; the other agents use
plain single searches.

```json
{"strategy": "mixed",
 "base": {"topic": "general", "search_depth": "basic", "country": "egypt", "max_results": 10},
 "searches": [
   {"name": "ar_restricted", "queries": "v2", "include_domains_mode": "restrict", "include_domains": ["..."]},
   {"name": "en_restricted", "queries": "v1", "include_domains_mode": "restrict", "include_domains": ["..."]},
   {"name": "open",          "queries": "v1"}]}
```

Each search sends `base` + its own settings, with the text of the same question id from its
query version (`v2` Arabic, `v1` English). `--queries` is ignored: the strategy picks them.
Run files go to `runs/<tool>/<settings>/queries_v1+v2/`.

`tavily_v3` (`mixed`):

| Search | Query | Domains |
|---|---|---|
| `ar_restricted` | Arabic (v2) | `restrict` to the 64 citable domains with `language` `ar` or `both` |
| `en_restricted` | English (v1) | `restrict` to the 90 citable domains with `language` `en` or `both` |
| `open` | English (v1) | none, same as `tavily_v1`, to catch good sources not in our lists yet |

Citable = `source_type` in `official`, `intl_official`, `news`, `business_news`,
`intl_news`, `consultancy_report`, `data_aggregator`, `listing_portal`, `travel_booking`,
`str_data`. The domain lists are written out in `tavily_v3.json` (generated once from the
CSVs on 2026-11-27, well under Tavily's 300 limit), so v3 stays the same when the CSVs change.

The run file holds each search under `searches` (name, query, status, seconds, error,
results and the raw response) and the merged results under `normalized`, ordered by the best
score any search gave, each with `found_by` (which searches returned it).

**Same URL** is decided by `merge.normalize_url` (in `merge.py`, used by both scripts): the
host is lowercased without `www.`, the trailing `/` is dropped, and the scheme, query string
and fragment are ignored, so `https://WWW.Youm7.com/story/1/?utm=x#top` and
`http://youm7.com/story/1` are one result. `score.py` merges each strategy run again from
its `searches` with this rule (it doesn't trust the saved `normalized`), so changing the
rule and rescoring applies it to old runs too. Because whole query strings are ignored,
pages told apart only by their query (e.g. `View.aspx?ID=21739` and `?ID=21741`) count as
one, and a search can then have fewer unique results than `<search>_n_results`.

A restricted search that finds nothing is saved as `empty` **without a retry** (our sites
may have nothing); the `open` search is retried once when empty, like a plain run. The run is
`error` only if every search failed. Cost: one credit per search, so 3 per question per run.

## Tools

| Tool | Key in `.env` | Function | API |
|---|---|---|---|
| `tavily` | `TAVILY_API_KEY` | `search_tavily` | official `tavily-python` SDK |
| `serper` | `SERPER_API_KEY` | `search_serper` | `POST https://google.serper.dev/search` with `httpx` (Google results) |

**Serper** sends exactly `{"q", "gl", "hl", "num"}` from the settings, with the key in the
`X-API-KEY` header (never saved or printed). Each item of `organic` becomes a result:
`link` → `url`, `title`, `snippet`, `date` → `published_date` (None if missing), and
`position` is kept as `position`. `score` is `1/position` (rank 1 → 1.0, rank 2 → 0.5), because
merging orders by score with higher = better, as Tavily's relevance score is. The full raw
response is saved (including `answerBox`, `knowledgeGraph`, `peopleAlsoAsk` when Google
returns them). A timeout or an HTTP error (429, 5xx, ...) is recorded as the search's error;
an empty `organic` is retried once (open search), then saved as `empty`.

Serper's `date` is the text Google shows, not a date: `3 days ago`, `Nov 16, 2026`, or in
Arabic results `قبل ٣ أيام` and `٠٧‏/١٢‏/٢٠٢٥`. `n_with_date` counts results that have one;
an agent would need to parse it before using it as a fact.

```bash
python -m experiments.tools.web_search.compare --tool serper --settings v1 --runs 2
```

## Add a tool

In `compare.py`, write one function and register it:

```python
def search_exa(query: str, settings: dict[str, Any]) -> tuple[Any, list[Result]]:
    raw = ...  # call the API with the key from _Keys (add exa_api_key there)
    return raw, [Result(url=..., title=..., snippet=..., published_date=..., score=...)]

TOOLS = {"tavily": search_tavily, "exa": search_exa}
```

Then add `settings/exa_v1.json` and the key to `.env`. `score.py` needs no change.
