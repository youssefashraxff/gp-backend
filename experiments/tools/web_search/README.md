# Web search tool comparison

Before the Market research and Segments agents pick a web search tool, we compare the tools
**directly, with no LLM involved**. An LLM in the loop would mix two questions, "is the tool
good?" and "did the model use it well?", so here the same 12 fixed queries (`queries.json`,
6 per test site) go straight to each tool, and we save and measure the raw results.

It is two steps:

| Step | Script | Calls an API? | Writes |
|---|---|---|---|
| 1. Collect | `compare.py` | yes | one new file per call in `runs/<tool>/<settings>/` (never overwritten) |
| 2. Score | `score.py` | no | `scores.csv`, `summary.csv` (regenerated), `manual.csv` (rows only added) |

Collecting costs credits; scoring is free. So when a source list changes, just rescore.

## Run

Put `TAVILY_API_KEY=...` in `.env` (never commit it), then:

```bash
# 1. collect: 12 queries x 2 runs (the default) = 24 calls
python -m experiments.tools.web_search.compare --tool tavily --settings v1 \
    --query all --notes "tavily v1 baseline"
python -m experiments.tools.web_search.compare --tool tavily --settings v1 \
    --query sokhna_q1 --runs 1        # one query, one call

# 2. score every run file under runs/ (all tools and settings)
python -m experiments.tools.web_search.score
```

Run files go in one folder per tool and settings version, e.g. `runs/tavily/v1/` and
`runs/tavily/v2/`, so rounds never mix. `manual.csv` is keyed by file name (which starts
with a unique time), so moving files between folders doesn't lose what you wrote.

`compare.py` saves the full raw response, the cleaned-up results, the query, settings, run
number, time, `status` and `--notes`. If a call returns 0 results without an error it
retries once; if still empty the run is saved with status `empty`. A failed call is saved
with status `error` and the run goes on.

`score.py` prints the share of all results per type at the end, for a quick overview.

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

Types without their own column (`lifestyle`, `academic`, `tourism_travel`, `maps_reviews`)
still count in `n_results`, and in `n_egyptian` when Egyptian.

## summary.csv (one row per tool + settings + query)

`runs`, `ok`, `empty`, `errors`, then `avg_<column>` for each count above (averaged over
the runs that didn't error), `same_top3` (how many `ok` runs share the most common top-3
set; order doesn't matter) and `avg_seconds`.

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

Add `settings/<tool>_v3.json` and run with `--settings v3`. Never edit a version that has
been run; old and new must stay comparable. Say what changed in `--notes`.

## Add a tool

In `compare.py`, write one function and register it:

```python
def search_exa(query: str, settings: dict[str, Any]) -> tuple[Any, list[Result]]:
    raw = ...  # call the API with the key from _Keys (add exa_api_key there)
    return raw, [Result(url=..., title=..., snippet=..., published_date=..., score=...)]

TOOLS = {"tavily": search_tavily, "exa": search_exa}
```

Then add `settings/exa_v1.json` and the key to `.env`. `score.py` needs no change.
