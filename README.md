# nixos-search-queries

Reproducible analysis comparing two search backends over NixOS packages and options:

- Elasticsearch 8.15.3
- Typesense 27.1

## What is a good search?

A good search wins on three axes at once, in priority order.

- **Relevance** — it returns the right answer and ranks it high, across every query shape you type: exact names, prefixes, typos, dotted option paths, and natural-language intent. This splits into finding the answer at all (Success@10), placing it near the top (MRR), and surfacing the whole family when several docs are correct (Recall@10).
- **Latency** — it responds fast enough to feel interactive, tail included. The median (p50) sets the typical feel, but the slow 1% (p99) is the lag you actually notice, so both are measured on warm caches.
- **Indexing cost** — it builds the index cheaply in time and footprint. This sets how often you can rebuild on a channel update and how much memory or disk the running service needs.

These axes trade off, so a good search balances all three rather than maximizing one. Richer relevance scoring costs latency, and serving from RAM costs footprint. This analysis measures all three, so the trade-off stays visible.

## What it measures

Corpus:

- packages: https://channels.nixos.org/<channel>/packages.json.br
- options:  https://channels.nixos.org/<channel>/options.json.br

`corpus/full.json`: 168,679 documents (144,174 packages + 24,505 options)

| Axis | Metrics |
| --- | --- |
| Relevance | Success@10, MRR, Recall@10 (+ per-category Success@10, paired 95% CI on MRR) |
| Latency | p50 / p95 / p99 / mean / max (ms), warm, fastest-of-5 per query |
| Indexing | full-index wall time, footprint |

Query set:

`queries/queries.json` holds 150 queries, 25 in each of six categories: exact, prefix, typo, dotted, multiterm, intent. Those queries carry 145 unique relevance labels. Every label exists in the corpus, so known-item scoring is mechanically sound.

Each label names a query's **canonical entry points**: the package doc(s) and the service's top-level `.enable` option. Deep sub-options stay unlabeled — they are the noise good ranking must rank below the entry points.

### Why only known-item metrics

No one can enumerate every relevant doc in a 168,679-doc corpus, so this analysis reports only known-item metrics — Success@10, MRR, Recall@10. Each stays valid because it is denominated by a query's labeled targets, not the whole corpus.

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

| metric | Elasticsearch | Typesense |
| --- | --- | --- |
| Success@10 | 0.800 | 0.740 |
| MRR | 0.609 | 0.604 |
| Recall@10 | 0.691 | 0.634 |

### Success@10 by query category (higher is better)

| category | Elasticsearch | Typesense |
| --- | --- | --- |
| exact | 1.000 | 1.000 |
| prefix | 0.800 | 0.960 |
| typo | 1.000 | 0.880 |
| dotted | 0.960 | 1.000 |
| multiterm | 0.640 | 0.440 |
| intent | 0.400 | 0.160 |

### Significance (paired MRR, Elasticsearch − Typesense, 95% bootstrap CI)

Positive favors Elasticsearch; `*` marks a CI that excludes 0.

| group | n | mean MRR diff | 95% CI |
| --- | --- | --- | --- |
| overall | 150 | +0.004 | [-0.051, +0.061] |
| exact | 25 | +0.033 | [+0.000, +0.100] |
| prefix | 25 | -0.236 | [-0.365, -0.122] * |
| typo | 25 | +0.165 | [+0.047, +0.305] * |
| dotted | 25 | -0.142 | [-0.269, -0.034] * |
| multiterm | 25 | +0.048 | [-0.126, +0.229] |
| intent | 25 | +0.159 | [+0.056, +0.283] * |

The engines tie overall on MRR: Elasticsearch leads `intent` and `typo`, Typesense leads `prefix` and `dotted`, and `exact` and `multiterm` are ties.

### Latency (ms, lower is better)

Typesense serves from RAM and runs about 4x faster at the median. Elasticsearch pays for its natural-language scoring path but holds p99 under 40 ms.

| stat | Elasticsearch | Typesense |
| --- | --- | --- |
| p50 | 15.55 | 3.95 |
| p95 | 32.42 | 13.16 |
| p99 | 37.36 | 17.84 |
| mean | 17.14 | 5.01 |
| max | 39.29 | 21.02 |

### Indexing (168,679 docs)

| metric | Elasticsearch | Typesense |
| --- | --- | --- |
| index time | 13.56 s | 11.85 s |
| footprint | 41 MB (on-disk store) | 174 MB (process RSS) |

Footprint uses each engine's native measure — Elasticsearch's on-disk Lucene store versus Typesense's in-RAM process RSS — so it is not comparable across engines.

## Conclusions

### Configuration dominates

On this corpus, how you tune an engine moves the result more than which engine you pick. Moving from the pre-tuning baseline to the best-practice config above raises overall Success@10 from 0.69 to 0.80 (Elasticsearch) and from 0.37 to 0.74 (Typesense). That change also turns a significant Elasticsearch MRR lead (+0.275) into a tie (+0.004). A no-regression gate (`scripts/tune.py`) locks these gains against a committed baseline (`results/baseline.json`). Every reported number reflects a deliberately tuned engine, not a default.

### Trade-offs are per-category

- Elasticsearch leads `intent` and `typo`.
- Typesense leads `prefix` and `dotted`.
- `exact` and `multiterm` are ties.

## Fairness

Both engines run a tuned, production-level configuration, not stock defaults. Each uses its own best-practice mechanism for the same capability, frozen as explicit config in code.

Both engines English-stem `description`, split dotted option paths into components, tolerate typos, match prefixes, and weight `name` over `description`. Both also privilege the short canonical name, so `nginx` and `services.nginx.enable` outrank deep paths that merely share a token.

- **Elasticsearch** (`engines/elasticsearch.py`): the `nixos_name` analyzer splits identifiers on `.`, `-`, `_`, and camelCase, and `preserve_original` keeps the whole token. A `.kw` sub-field does exact match. A `.prefix` edge-ngram sub-field does leading-substring match. `search` sums a `dis_max` (tie_breaker 0.3) over four clauses — a fuzzy `multi_match` (`name^3`, `description`), a `.prefix` match (boost 2), an exact `name.kw` term (boost 5), and a `description` match gated to ≥2 terms (`minimum_should_match: 2`) — plus a `shortness` rank_feature (`100/len(name)`).
- **Typesense** (`engines/typesense.py`): the schema sets `token_separators` `["-", "."]` and stems `description` at field level. Search pins per-field typo (`num_typos=2,1`), prefix (`prefix=true,false`), `split_join_tokens=fallback`, `prioritize_exact_match`, `text_match_type=max_score`, and `query_by_weights` `3,1`. The key lever is `sort_by: _text_match(buckets: 4):desc, name_len:asc`, which buckets by match score, then ranks the shorter name first — the analogue of Elasticsearch's BM25 fieldNorm.

Both engines run on the same host via `docker-compose.yml` with 2 GB memory limits and pinned versions.

Both engines answer the same queries, so the comparison is paired. Significance follows one rule: the 95% CI must exclude 0. At 25 queries per category, only moderate-to-large effects resolve. Smaller gaps show as CIs that straddle 0.

## Known limitations

1. **camelCase splitting is Elasticsearch-only.** Elasticsearch splits `virtualHosts` into `virtual` and `hosts`. Typesense has no equivalent, and `infix` stays off because it does substring matching at a real latency cost.
2. **Relevance judgments are opinionated.** Only a canonical entry point counts — a package or a module's top-level `.enable` — so labeling `.package` or `.settings` too would move the numbers.
3. **Judgments are incomplete on the full corpus.** Only entry points are labeled, which is why Precision and nDCG cannot be reported.
4. **Relevance cost some Elasticsearch latency.** The natural-language clause and rank_feature raise Elasticsearch to p50 ~16 ms and p99 ~37 ms, while Typesense's `sort_by` stays near-free at p99 ~18 ms.
5. **Category weighting is uniform.** All six categories weigh equally, but real search.nixos.org traffic skews toward name and prefix queries, so a traffic-weighted verdict needs query-mix data.

## Layout

```
corpus/full.json          168,679-doc packages+options corpus
queries/queries.json      150 labeled queries (145 unique canonical-entry-point labels)
searcheval/
  schema.py               Doc/Query model + NixOS JSON normalization
  metrics.py              pure ranking/latency metrics
  harness.py              known-item relevance + latency/indexing in one pass
  report.py               Markdown matrix + raw per-query JSON
  stats.py                paired-bootstrap significance test
  engines/                Elasticsearch + Typesense adapters (SearchEngine ABC)
  cli.py                  searcheval entry point
  fetch_corpus.py         searcheval-fetch-corpus: full packages+options dataset
scripts/tune.py           no-regression gate against results/baseline.json
tests/                    metrics/schema/harness/queryset unit tests
```

## Reproduce

```sh
docker compose up -d
nix run . -- --corpus corpus/full.json --queries queries/queries.json
```

The run writes `results/report.md` (side-by-side matrix) and `results/raw_<engine>.json` (every ranked result plus per-query latency), so any headline number traces back to a specific query. Restrict to one engine with `--engine typesense` (repeatable), and point `--corpus` at a smaller file for a fast dev run. Run `python scripts/tune.py check` to re-verify the no-regression gate.

## Development

```sh
nix develop
pytest
```

Metrics and normalization are pure functions with exact-value tests, the harness is covered end-to-end with an in-process fake engine, and `tests/test_queryset.py` locks the judged set's validity invariants. The live Elasticsearch/Typesense comparison needs the Docker services up.
