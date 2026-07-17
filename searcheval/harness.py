"""Run an engine over the full corpus and score known-item relevance + latency.

``evaluate`` indexes the single full corpus once per engine and scores it:
    wait_ready -> reset -> index (timed) -> warmup -> timed query loop -> score

Relevance is scored with known-item metrics (Success@10, MRR, Recall@10) that
stay valid when the corpus is not exhaustively judged: they are denominated by
the query's labeled targets, not by the whole corpus, so genuine-but-unlabeled
docs never bias them. Precision and nDCG are intentionally not computed here.

Latency and indexing come from the same pass: every query is run ``repeat``
times and the fastest run feeds latency stats (minimizes GC/scheduler noise),
while relevance is scored once per query (ranking is deterministic for a fixed
index). The ``IndexStats`` from the timed index build supplies the footprint.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import metrics
from .engines.base import IndexStats, SearchEngine
from .schema import Doc, Query


@dataclass
class QueryResult:
    id: str
    q: str
    category: str
    ranked: list[str]
    relevant: list[str]
    latency_ms: float
    recall_at_10: float
    mrr: float
    success_at_10: float


@dataclass
class EngineReport:
    engine: str
    index_stats: IndexStats
    results: list[QueryResult] = field(default_factory=list)

    def aggregate(self) -> dict:
        n = len(self.results) or 1
        agg = {
            "queries": len(self.results),
            "recall@10": sum(r.recall_at_10 for r in self.results) / n,
            "mrr": sum(r.mrr for r in self.results) / n,
            "success@10": sum(r.success_at_10 for r in self.results) / n,
        }
        agg["latency"] = metrics.latency_summary([r.latency_ms for r in self.results])
        agg["index"] = {
            "doc_count": self.index_stats.doc_count,
            "seconds": self.index_stats.seconds,
            "index_bytes": self.index_stats.index_bytes,
            "footprint_kind": self.index_stats.footprint_kind,
        }
        agg["by_category"] = self._by_category()
        return agg

    def _by_category(self) -> dict:
        cats: dict[str, list[QueryResult]] = {}
        for r in self.results:
            cats.setdefault(r.category, []).append(r)
        out = {}
        for cat, rs in sorted(cats.items()):
            m = len(rs)
            out[cat] = {
                "queries": m,
                "mrr": sum(r.mrr for r in rs) / m,
                "success@10": sum(r.success_at_10 for r in rs) / m,
            }
        return out


def _fastest_search(engine: SearchEngine, q: str, k: int,
                    repeat: int) -> tuple[float, list[str]]:
    """Run ``q`` ``repeat`` times, return (fastest ms, last ranking).

    Fastest-of-N minimizes GC/scheduler noise in the latency figure. The
    ranking is deterministic for a fixed index, so any run's ids are valid."""
    best_ms = float("inf")
    ranked: list[str] = []
    for _ in range(max(1, repeat)):
        t0 = time.perf_counter()
        ranked = engine.search(q, k)
        dt = (time.perf_counter() - t0) * 1000
        best_ms = min(best_ms, dt)
    return best_ms, ranked


def evaluate(engine: SearchEngine, docs: list[Doc], queries: list[Query],
             k: int = 10, repeat: int = 5, warmup: int = 2) -> EngineReport:
    engine.wait_ready()
    engine.reset()
    stats = engine.index(docs)

    # Warm caches so first-query cost doesn't pollute the latency distribution.
    for _ in range(warmup):
        for query in queries:
            engine.search(query.q, k)

    report = EngineReport(engine=engine.name, index_stats=stats)
    for query in queries:
        best_ms, ranked = _fastest_search(engine, query.q, k, repeat)
        rel = query.relevant
        report.results.append(QueryResult(
            id=query.id, q=query.q, category=query.category,
            ranked=ranked, relevant=sorted(rel), latency_ms=best_ms,
            recall_at_10=metrics.recall_at_k(ranked, rel, 10),
            mrr=metrics.reciprocal_rank(ranked, rel),
            success_at_10=metrics.success_at_k(ranked, rel, 10),
        ))
    return report
