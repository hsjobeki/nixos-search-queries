"""Build the combined JSON payload the static visualization renders from.

The published site (``docs/index.html``) is entirely data-driven: it fetches one
``docs/data.json`` and iterates over whatever engines and categories appear in it.
This module produces that payload from the per-engine ``results/raw_<engine>.json``
dumps written by ``report.write_raw``.

Two reasons the site reads a generated file instead of the raw dumps directly:

- ``results/`` is gitignored; GitHub Pages serves ``docs/``. The published data
  MUST live under ``docs/``.
- Significance needs the paired bootstrap (``stats.paired_bootstrap_ci``, seeded).
  Keeping it in Python via ``report.significance_rows`` is one deterministic source
  of truth, rather than a re-implemented (and nondeterministic) bootstrap in JS.

The payload is keyed so the query explorer can look up every engine's ranking for
one query in a single place: ``queries[i].engines[<engine>]``.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

from .engines.base import IndexStats
from .harness import EngineReport, QueryResult
from .report import significance_rows


def load_report(path: str | Path) -> EngineReport:
    """Reconstruct an ``EngineReport`` from a ``raw_<engine>.json`` dump.

    Co-locates knowledge of the raw-file schema here (one tested place) so the
    build script stays a thin IO wrapper. ``summary["index"]`` carries exactly the
    ``IndexStats`` fields; the per-query ``recall@10``/``success@10`` keys map onto
    the dataclass's ``recall_at_10``/``success_at_10``.
    """
    data = json.loads(Path(path).read_text())
    stats = IndexStats(**data["summary"]["index"])
    results = [
        QueryResult(
            id=e["id"], q=e["q"], category=e["category"],
            ranked=e["ranked"], relevant=e["relevant"],
            latency_ms=e["latency_ms"],
            recall_at_10=e["recall@10"], mrr=e["mrr"],
            success_at_10=e["success@10"],
        )
        for e in data["per_query"]
    ]
    return EngineReport(engine=data["engine"], index_stats=stats, results=results)


def build_site_data(reports: list[EngineReport], *,
                    versions: dict[str, str] | None = None) -> dict:
    """Assemble the single combined payload the static page renders from.

    Engines are sorted so colors/columns are stable across rebuilds and a new
    backend simply appends. Queries are aligned by id (all engines answer the same
    set); query-level fields (``q``/``category``/``relevant``) are taken from the
    first engine and asserted identical across the rest — a mismatch means the raw
    dumps came from different query sets and the comparison would be meaningless.
    """
    if not reports:
        raise ValueError("need at least one engine report to build site data")

    reports = sorted(reports, key=lambda r: r.engine)
    engines = [r.engine for r in reports]
    by_engine = {r.engine: {res.id: res for res in r.results} for r in reports}
    ref = reports[0]
    # Max top-k any engine actually returned, exposed as metadata.
    cutoff = max((len(res.ranked) for r in reports for res in r.results), default=0)

    queries = []
    for res in ref.results:
        entry = {
            "id": res.id, "q": res.q, "category": res.category,
            "relevant": res.relevant,
            "engines": {},
        }
        for eng in engines:
            r = by_engine[eng].get(res.id)
            if r is None:
                continue
            if not (r.q == res.q and r.category == res.category
                    and r.relevant == res.relevant):
                raise ValueError(
                    f"query {res.id!r} differs across engines; raw dumps disagree")
            entry["engines"][eng] = {
                "ranked": r.ranked,
                "latency_ms": r.latency_ms,
                "mrr": r.mrr,
                "recall@10": r.recall_at_10,
                "success@10": r.success_at_10,
            }
        queries.append(entry)

    # Significance needs a pair; with one engine there is nothing to compare.
    significance = [
        {"a": a.engine, "b": b.engine,
         "rows": significance_rows(a.results, b.results)}
        for a, b in itertools.combinations(reports, 2)
    ]

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "doc_count": ref.index_stats.doc_count,
            "cutoff": cutoff,
            "versions": versions or {},
        },
        "engines": engines,
        "summaries": {r.engine: r.aggregate() for r in reports},
        "queries": queries,
        "significance": significance,
    }


def write_site(reports: list[EngineReport], out_dir: str | Path = "docs", *,
               versions: dict[str, str] | None = None) -> Path:
    """Write ``<out_dir>/data.json`` (the artifact GitHub Pages serves)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "data.json"
    payload = build_site_data(reports, versions=versions)
    path.write_text(json.dumps(payload, indent=2))
    return path
