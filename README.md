# nixos-search-queries

Reproducible analysis comparing three search backends over NixOS packages and options:

- Elasticsearch 8.15.3
- Typesense 27.1
- Quickwit 0.8.2

## What is a good search?

A good search wins on three axes at once, in priority order.

- **Relevance** — returns the right answer and ranks it high, across every query shape you type: exact names, prefixes, typos, dotted option paths, natural-language intent. Three parts: finding the answer at all (Success@10), placing it near the top (MRR), surfacing the whole family when several docs are correct (Recall@10).
- **Latency** — responds fast enough to feel interactive, tail included. p50 sets the typical feel; p99 is the lag you actually notice. Both are measured on warm caches.
- **Indexing cost** — builds the index cheaply in time and footprint. This sets how often you can rebuild on a channel update, and how much memory or disk the running service needs.

These axes trade off. Richer relevance scoring costs latency; serving from RAM costs footprint. A good search balances all three rather than maximizing one. This analysis measures all three, so the trade-off stays visible.

## What it measures

Corpus:

- packages: `https://channels.nixos.org/<channel>/packages.json.br`
- options: `https://channels.nixos.org/<channel>/options.json.br`

`corpus/full.json`: 168,679 documents (144,174 packages + 24,505 options)

| Axis | Metrics |
| --- | --- |
| Relevance | Success@10, MRR, Recall@10 (+ per-category Success@10, paired 95% CI on MRR) |
| Latency | p50 / p95 / p99 / mean / max (ms), warm, fastest-of-5 per query |
| Indexing | full-index wall time, footprint |

Query set:

`queries/queries.json` holds 150 queries: 25 in each of six categories — exact, prefix, typo, dotted, multiterm, intent. They carry 145 unique relevance labels. Every label exists in the corpus, so known-item scoring is mechanically sound.

Each label names a query's **canonical entry points**: the package doc(s) and the service's top-level `.enable` option. Deep sub-options stay unlabeled. Good ranking must rank them below the entry points — they are noise.

### Why only known-item metrics

No one can enumerate every relevant doc in a 168,679-doc corpus. So this analysis reports only known-item metrics: Success@10, MRR, Recall@10. Each is denominated by a query's labeled targets, not the whole corpus, so each stays valid.

Precision and nDCG are omitted by design. On an unlabeled corpus, they count genuine-but-unlabeled hits as misses — unequally per engine — which would bias the comparison.

## Reading the numbers

- **Success@10** (0–1): the correct answer appears somewhere in the top 10; 0.80 means it did for 80% of queries.
- **MRR** (0–1): how high the first correct answer ranks, averaged over queries; 1.0 is always rank 1, 0.5 is typically rank 2.
- **Recall@10** (0–1): the share of a query's correct answers that reach the top 10.
- **p50 / p95 / p99** (ms): the median, worst-5%, and worst-1% query latencies; under ~100 ms feels instant.
- **warm, fastest-of-5**: each query runs several times after cache warm-up, keeping the fastest run to measure steady-state speed.

## Results

Single-node Docker host, warm caches, fastest-of-5 per query.

### Relevance (higher is better)

| metric | Elasticsearch | Quickwit | Typesense |
| --- | --- | --- | --- |
| Success@10 | 0.800 | 0.400 | 0.740 |
| MRR | 0.609 | 0.306 | 0.604 |
| Recall@10 | 0.691 | 0.373 | 0.634 |

### Success@10 by query category (higher is better)

| category | Elasticsearch | Quickwit | Typesense |
| --- | --- | --- | --- |
| dotted | 0.960 | 1.000 | 1.000 |
| exact | 1.000 | 1.000 | 1.000 |
| intent | 0.400 | 0.080 | 0.160 |
| multiterm | 0.640 | 0.200 | 0.440 |
| prefix | 0.800 | 0.080 | 0.960 |
| typo | 1.000 | 0.040 | 0.880 |

Quickwit ties on `exact` and `dotted` (both 1.000): its raw-token clause pins exact-name and full-path lookups directly. It falls far behind on `typo` (0.040) and `prefix` (0.080). Both gaps are structural, not tuning:

- No fuzzy / edit-distance query. A misspelling that is not a clean prefix simply misses.
- No `rank_feature` or score-bucketing lever. A short canonical option cannot outrank the many longer docs sharing a prefix token.

### Significance (paired MRR, 95% bootstrap CI)

Positive favors the first engine. `*` marks a CI that excludes 0. Three engines make three pairs. Read individual per-category stars cautiously: with six category CIs per pair across three pairs, some exclude 0 by chance. The overall rows and large effects are robust.

#### Elasticsearch − Quickwit

| group | n | mean MRR diff | 95% CI |
| --- | --- | --- | --- |
| overall | 150 | +0.303 | [+0.230, +0.376] * |
| dotted | 25 | +0.031 | [-0.098, +0.168] |
| exact | 25 | +0.000 | [+0.000, +0.000] |
| intent | 25 | +0.210 | [+0.087, +0.353] * |
| multiterm | 25 | +0.234 | [+0.080, +0.400] * |
| prefix | 25 | +0.498 | [+0.334, +0.655] * |
| typo | 25 | +0.842 | [+0.669, +0.980] * |

#### Elasticsearch − Typesense

| group | n | mean MRR diff | 95% CI |
| --- | --- | --- | --- |
| overall | 150 | +0.004 | [-0.051, +0.061] |
| dotted | 25 | -0.142 | [-0.269, -0.034] * |
| exact | 25 | +0.033 | [+0.000, +0.100] |
| intent | 25 | +0.159 | [+0.056, +0.283] * |
| multiterm | 25 | +0.048 | [-0.126, +0.229] |
| prefix | 25 | -0.236 | [-0.365, -0.122] * |
| typo | 25 | +0.165 | [+0.047, +0.305] * |

#### Quickwit − Typesense

| group | n | mean MRR diff | 95% CI |
| --- | --- | --- | --- |
| overall | 150 | -0.298 | [-0.371, -0.227] * |
| dotted | 25 | -0.173 | [-0.334, -0.025] * |
| exact | 25 | +0.033 | [+0.000, +0.100] |
| intent | 25 | -0.051 | [-0.151, +0.023] |
| multiterm | 25 | -0.187 | [-0.320, -0.073] * |
| prefix | 25 | -0.734 | [-0.855, -0.602] * |
| typo | 25 | -0.678 | [-0.857, -0.470] * |

Elasticsearch and Typesense tie overall on MRR (+0.004). Elasticsearch leads `intent` and `typo`; Typesense leads `prefix` and `dotted`. Quickwit trails both by ~0.30 overall MRR — almost all from `prefix` and `typo` — but is statistically level on `exact` and `dotted`.

### Latency (ms, lower is better)

| stat | Elasticsearch | Quickwit | Typesense |
| --- | --- | --- | --- |
| p50 | 11.27 | 14.94 | 3.93 |
| p95 | 22.32 | 17.07 | 13.18 |
| p99 | 28.67 | 58.38 | 16.50 |
| mean | 12.77 | 14.98 | 4.83 |
| max | 29.40 | 59.02 | 18.82 |

Typesense serves from RAM and is fastest at the median (~4x). Quickwit's median sits near Elasticsearch's. But its tail is the widest here (p99 ~58 ms), from split-store reads under scored sort.

### Indexing (168,679 docs)

| metric | Elasticsearch | Quickwit | Typesense |
| --- | --- | --- | --- |
| index time | 11.67 s | 3.02 s | 10.48 s |
| footprint | 40 MB (on-disk store) | 15 MB (on-disk split store) | 173 MB (process RSS) |

Quickwit indexes fastest (one forced commit into a single split) and has the smallest footprint. Footprint uses each engine's native measure:

- Elasticsearch and Quickwit report on-disk store size. Roughly comparable.
- Typesense reports in-RAM process RSS. A different quantity, not comparable to either.

## Conclusions

### Configuration dominates

Among engines with the right levers, how you tune moves the result more than which engine you pick. From the pre-tuning baseline to the best-practice config, overall Success@10 rises:

- Elasticsearch: 0.69 → 0.80
- Typesense: 0.37 → 0.74

That change also turns a significant Elasticsearch MRR lead (+0.275) into a tie (+0.004). A no-regression gate (`scripts/tune.py`) locks these gains against a committed baseline (`baseline.json`). Every reported number reflects a tuned engine, not a default.

### Some gaps are structural, not tuning

Quickwit is the counter-example. Its low `typo` (0.040) and `prefix` (0.080) come from missing capabilities, not mis-tuning. Quickwit 0.8.x has no fuzzy / edit-distance query and no `rank_feature` or score-bucketing lever, and neither is reachable through its REST API. So a faithful adapter cannot match typo tolerance or the short-canonical-name privilege the others use. That is the honest ceiling of the engine on this workload. Emulating the missing features (n-gram typo expansion, a hand-rolled shortness prior) would make the comparison unfair, not better.

### Trade-offs are per-category

- Elasticsearch leads `intent` and `typo`, and beats Quickwit on every category that is not a tie.
- Typesense leads `prefix` and `dotted` (vs Elasticsearch) and beats Quickwit everywhere except the ties.
- Quickwit ties the field on `exact` and `dotted`; it trails on `prefix`, `typo`, `intent`, and `multiterm`.
- `exact` is a three-way tie.

## Fairness

All three engines run a tuned, production-level configuration, not stock defaults. Each uses its own best-practice mechanism for the same capability, frozen as explicit config in code.

All three: English-stem `description`, split dotted option paths into components, match prefixes, and weight `name` over `description`. Elasticsearch and Typesense also tolerate typos and privilege the short canonical name, so `nginx` and `services.nginx.enable` outrank deep paths that merely share a token. Quickwit can do neither through its REST API; that gap is reported below, not hidden.

- **Elasticsearch** (`engines/elasticsearch.py`):
  - `nixos_name` analyzer splits identifiers on `.`, `-`, `_`, and camelCase; `preserve_original` keeps the whole token.
  - `.kw` sub-field does exact match. `.prefix` edge-ngram sub-field does leading-substring match.
  - `search` sums a `dis_max` (tie_breaker 0.3) over four clauses: fuzzy `multi_match` (`name^3`, `description`), `.prefix` match (boost 2), exact `name.kw` term (boost 5), `description` match gated to ≥2 terms (`minimum_should_match: 2`).
  - Plus a `shortness` rank_feature (`100/len(name)`).
- **Typesense** (`engines/typesense.py`):
  - Schema sets `token_separators` `["-", "."]` and stems `description` at field level.
  - Search pins per-field typo (`num_typos=2,1`), prefix (`prefix=true,false`), `split_join_tokens=fallback`, `prioritize_exact_match`, `text_match_type=max_score`, and `query_by_weights` `3,1`.
  - Key lever: `sort_by: _text_match(buckets: 4):desc, name_len:asc` — bucket by match score, then rank the shorter name first. The analogue of Elasticsearch's BM25 fieldNorm.
- **Quickwit** (`engines/quickwit.py`):
  - Doc mapping tokenizes `name` on `.`/`-`/punctuation, English-stems `description`, and keeps a raw whole-string `name_raw` field for exact match (the `name.kw` analogue).
  - Indexes through the native ingest endpoint. Queries through the native search endpoint with a query-language expression whose per-clause `^` boosts mirror the same weighting: name terms (3) + description terms (1), a last-token prefix (2), an exact `name_raw` phrase (5). Sorted `_score` then `name_len`.
  - Two load-bearing capability gaps, reported not worked around:
    - **No fuzzy / edit-distance query.** The `typo` category is handicapped — a misspelling that is not a clean prefix cannot match.
    - **No `rank_feature` and no score bucketing.** The short-canonical-name privilege leans only on BM25 fieldnorms plus a rarely-firing `_score,name_len` tie-break, so `prefix` collapses (target is a long `services.X.enable` option).
  - Also lacks a camelCase splitter (like Typesense) and `preserve_original` (compensated by `name_raw`).
  - The Elasticsearch-compatible `_search` endpoint is deliberately unused: sorting by `_score` on `match`/`bool` queries 500s over local split storage in 0.8.x. The native endpoint's `sort_by=_score` is unaffected.

All three engines run on the same host via `docker-compose.yml` with 2 GB memory limits and pinned versions.

All engines answer the same queries, so each pairwise comparison is paired. One rule for significance: the 95% CI must exclude 0. At 25 queries per category, only moderate-to-large effects resolve. Smaller gaps straddle 0. Three engines run all three pairs, so apply a multiple-comparison caveat to individual per-category stars. The overall rows and large effects are unaffected.

## Known limitations

1. **camelCase splitting is Elasticsearch-only.** Elasticsearch splits `virtualHosts` into `virtual` and `hosts`. Neither Typesense nor Quickwit has an equivalent. Typesense's `infix` stays off: substring matching at a real latency cost.
2. **Quickwit has no fuzzy matching.** Quickwit 0.8.x exposes no edit-distance query. The `typo` category (0.040) only scores when a misspelling is a clean prefix of the real token. N-gram emulation is out of scope: bespoke and unfair.
3. **Quickwit's short-name privilege is weak.** With no `rank_feature` or score bucketing, a short canonical option cannot be lifted above the many longer docs sharing a prefix token. That floors `prefix` (0.080). The `_score,name_len` tie-break rarely fires because BM25 ties are rare.
4. **Quickwit ingest reports no per-doc errors.** The ingest API returns only a processing count. So the adapter count-verifies `num_published_docs` via `/describe` after indexing. Otherwise a silently dropped document would deflate recall undetected.
5. **Quickwit's Elasticsearch-compatible `_search` sort is broken on local storage.** In 0.8.x, sorting by `_score` on `match`/`bool` queries 500s ("StorageDirectory only supports async operations"). The adapter uses the native search endpoint instead. Do not "fix" it back to the ES DSL.
6. **Relevance judgments are opinionated.** Only a canonical entry point counts — a package or a module's top-level `.enable`. Labeling `.package` or `.settings` too would move the numbers.
7. **Judgments are incomplete on the full corpus.** Only entry points are labeled. That is why Precision and nDCG cannot be reported.
8. **Relevance costs some latency.**
   - Elasticsearch: natural-language clause + rank_feature → p50 ~11 ms / p99 ~29 ms.
   - Quickwit: scored split-store reads → widest tail (p99 ~58 ms).
   - Typesense: `sort_by` stays near-free (p99 ~17 ms).
9. **Category weighting is uniform.** All six categories weigh equally. But real search.nixos.org traffic skews toward name and prefix queries. A traffic-weighted verdict needs query-mix data.

## Layout

```
corpus/full.json          168,679-doc packages+options corpus
queries/queries.json      150 labeled queries (145 unique canonical-entry-point labels)
baseline.json             locked pre-tuning yardstick for scripts/tune.py
searcheval/
  schema.py               Doc/Query model + NixOS JSON normalization
  metrics.py              pure ranking/latency metrics
  harness.py              known-item relevance + latency/indexing in one pass
  report.py               Markdown matrix + raw per-query JSON
  stats.py                paired-bootstrap significance test
  site.py                 combined data.json payload for the visualization
  engines/                Elasticsearch + Typesense + Quickwit adapters (SearchEngine ABC)
  cli.py                  searcheval entry point
  fetch_corpus.py         searcheval-fetch-corpus: full packages+options dataset
scripts/
  tune.py                 no-regression gate against baseline.json
  build_site.py           regenerate docs/data.json from results/raw_*.json
docs/                     interactive static visualization (index.html + data.json, GitHub Pages)
tests/                    metrics/schema/harness/engines/report/site/queryset unit tests
```

## Reproduce

```sh
docker compose up -d
nix run . -- --corpus corpus/full.json --queries queries/queries.json
```

The run writes two files:

- `results/report.md` — side-by-side matrix.
- `results/raw_<engine>.json` — every ranked result plus per-query latency.

So any headline number traces back to a specific query. `docker compose up -d` starts all three engines. Restrict the run with `--engine quickwit` (repeatable). Point `--corpus` at a smaller file for a fast dev run. Run `python scripts/tune.py check` to re-verify the no-regression gate.

## Visualization

An interactive dashboard lives in `docs/`, served as GitHub Pages

```sh
python scripts/build_site.py
```

Preview locally

```sh
python -m http.server -d docs 8000   # then open http://localhost:8000/
```

To add a new backend: implement the adapter → run the eval → `python scripts/build_site.py` → commit `docs/`.

## Development

```sh
nix develop
pytest
```

The test suite covers each layer:

- Exact-value tests cover the pure metrics and normalization functions.
- An in-process fake engine covers the harness end-to-end.
- `tests/test_engines.py` locks the engine registry and Quickwit's config and query shapes.
- `tests/test_report.py` locks the N-engine significance rendering.
- `tests/test_queryset.py` locks the judged set's validity invariants.
- `tests/test_site.py` locks the engine-agnostic visualization payload builder.

The live Elasticsearch, Typesense, and Quickwit comparison needs the Docker services up.
