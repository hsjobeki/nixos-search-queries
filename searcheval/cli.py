"""CLI: run the search backend evaluation.

    searcheval --corpus corpus/full.json --queries queries/queries.json

Relevance, latency and indexing are all measured on a single corpus (the full
168,679-doc packages+options corpus by default). Relevance uses known-item
metrics (Success@10, MRR, Recall@10) that stay valid when the corpus is not
exhaustively judged. Requires the target engines to be reachable (see
docker-compose.yml). Select a subset with ``--engine``.
"""

from __future__ import annotations

import argparse
import sys

from . import report as report_mod
from .engines import ENGINES
from .harness import evaluate
from .schema import load_corpus, load_queries, validate_queries


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Elasticsearch vs Typesense vs Quickwit over NixOS data")
    ap.add_argument("--corpus", default="corpus/full.json",
                    help="corpus indexed for relevance + latency + indexing "
                         "(point at a smaller file for a fast dev run)")
    ap.add_argument("--queries", default="queries/queries.json")
    ap.add_argument("--engine", action="append", choices=sorted(ENGINES),
                    help="restrict to these engines (default: all)")
    ap.add_argument("--out", default="results")
    ap.add_argument("-k", type=int, default=10, help="result cutoff")
    ap.add_argument("--repeat", type=int, default=5, help="timed runs per query")
    ap.add_argument("--es-url", default="http://localhost:9200")
    ap.add_argument("--ts-url", default="http://localhost:8108")
    ap.add_argument("--ts-key", default="evalkey")
    ap.add_argument("--qw-url", default="http://localhost:7280")
    args = ap.parse_args(argv)

    docs = load_corpus(args.corpus)
    queries = load_queries(args.queries)

    problems = validate_queries(queries, docs)
    if problems:
        print("Golden set references unknown doc ids; fix before scoring:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    selected = args.engine or sorted(ENGINES)
    reports = []
    for name in selected:
        print(f"[{name}] indexing {len(docs)} docs, running {len(queries)} queries...")
        with _build(name, args) as engine:
            rep = evaluate(engine, docs, queries, k=args.k, repeat=args.repeat)
        reports.append(rep)
        report_mod.write_raw(rep, args.out)

    matrix = report_mod.write_matrix(reports, args.out)
    print(f"\nWrote {matrix} and raw per-query dumps to {args.out}/")
    print(matrix.read_text())
    return 0


def _build(name: str, args):
    cls = ENGINES[name]
    if name == "elasticsearch":
        return cls(url=args.es_url)
    if name == "typesense":
        return cls(url=args.ts_url, api_key=args.ts_key)
    if name == "quickwit":
        return cls(url=args.qw_url)
    return cls()  # pragma: no cover - registry is exhaustive


if __name__ == "__main__":
    raise SystemExit(main())
