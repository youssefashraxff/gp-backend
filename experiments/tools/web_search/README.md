# Web search tool comparison

Before the Market research and Segments agents pick a web search tool, we compare the tools
**directly, with no LLM involved**. An LLM in the loop would mix two questions, "is the tool
good?" and "did the model use it well?", so here the same 12 fixed queries (`queries.json`,
6 per test site) go straight to each tool several times, and we save and measure the raw
results.

## Run

Put `TAVILY_API_KEY=...` in `.env` (never commit it), then:

```bash
python -m experiments.tools.web_search.compare --tool tavily --settings v1 --runs 8 \
    --query all --notes "first baseline"
python -m experiments.tools.web_search.compare --tool tavily --settings v1 --runs 3 \
    --query sokhna_q1
```

Each call saves its full raw response to
`runs/<time>__<tool>__<settings>__<query_id>__run<n>.json` (never overwritten) and appends
one row to `results.csv`. At the end it prints, per query, the average results, the average
Egyptian results and how stable the top 3 was. A failed call is recorded in the `error`
column and the run goes on. `--runs 8 --query all` is 96 calls (about 96 Tavily credits on
`basic`).

## results.csv columns

| Column | Meaning |
|---|---|
| `timestamp` | When the call was made (UTC) |
| `tool`, `settings` | Tool name and settings version, e.g. `tavily`, `v1` |
| `query_version`, `query_id`, `site`, `group` | Which query, from `queries.json` |
| `run` | Run number for this query in this command (1..N) |
| `n_results` | How many results came back |
| `n_egyptian` | Results whose domain ends in `.eg` or is listed in `egypt_domains.txt` |
| `n_with_date` | Results with a `published_date` |
| `n_unique_domains` | How many different domains the results come from |
| `top3_urls` | The first three URLs, joined by ` \| ` |
| `seconds` | How long the call took |
| `error` | The error, if the call failed; empty otherwise |
| `relevant` | Filled in **by hand** (see below) |
| `notes` | What `--notes` said: what this run was trying |

## Filling in `relevant`

Open the run file named by the row's timestamp, tool, query and run, read the results, and
write in `relevant` how many of them actually help answer the query for that site (a number
0..`n_results`). Count a result only if it is about the right place and gives usable
information (a price, a project, a number, a source we could cite). Judge one query across
all tools before moving to the next, so the standard stays the same.

If you see an Egyptian site that wasn't counted, add its domain to `egypt_domains.txt`.

## Add a settings version

Add `settings/<tool>_v2.json` and run with `--settings v2`. Never edit a version that has
been run; old and new must stay comparable. Say what changed in `--notes`.

## Add a tool

In `compare.py`, write one function and register it:

```python
def search_exa(query: str, settings: dict[str, Any]) -> tuple[Any, list[Result]]:
    raw = ...  # call the API with the key from _Keys (add exa_api_key there)
    return raw, [Result(url=..., title=..., snippet=..., published_date=..., score=...)]

TOOLS = {"tavily": search_tavily, "exa": search_exa}
```

Then add `settings/exa_v1.json` and the key to `.env`. Nothing else changes.
