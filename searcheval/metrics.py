"""Pure ranking/latency metrics. No engine or IO dependencies.

All ranking metrics take ``ranked`` (ordered list of returned doc ids, best
first) and ``relevant`` (set of ids that are correct answers). Binary relevance.
"""

from __future__ import annotations

import math
from statistics import mean


def recall_at_k(ranked: list[str], relevant: set[str] | frozenset[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for d in ranked[:k] if d in relevant)
    return hits / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: set[str] | frozenset[str]) -> float:
    """1/rank of the first relevant hit; 0 if none found."""
    for i, d in enumerate(ranked, start=1):
        if d in relevant:
            return 1.0 / i
    return 0.0


def success_at_k(ranked: list[str], relevant: set[str] | frozenset[str], k: int) -> float:
    """1.0 if any relevant doc appears in the top-k, else 0.0 (a.k.a. hit rate).

    This is the metric of choice for canonical-answer evaluation: it asks "did the
    right result surface at all in the top-k" and, unlike precision, does not
    penalize the many valid-but-unlabeled results a large corpus returns."""
    return 1.0 if any(d in relevant for d in ranked[:k]) else 0.0

def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (p in [0,100]). Empty -> 0.0."""
    if not values:
        return 0.0
    if not 0 <= p <= 100:
        raise ValueError("p must be within [0, 100]")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (p / 100) * (len(s) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return s[lo]
    frac = rank - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def latency_summary(latencies_ms: list[float]) -> dict[str, float]:
    if not latencies_ms:
        return {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {
        "count": len(latencies_ms),
        "mean": mean(latencies_ms),
        "p50": percentile(latencies_ms, 50),
        "p95": percentile(latencies_ms, 95),
        "p99": percentile(latencies_ms, 99),
        "max": max(latencies_ms),
    }
