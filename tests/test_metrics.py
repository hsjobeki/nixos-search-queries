"""Metrics are the scoring core; wrong metrics silently invalidate the whole
evaluation. These lock down exact expected values, not just 'runs without error'.
"""

import pytest

from searcheval import metrics


def test_recall_at_k():
    ranked = ["a", "x", "b"]
    rel = {"a", "b", "c"}
    assert metrics.recall_at_k(ranked, rel, 10) == pytest.approx(2 / 3)
    assert metrics.recall_at_k(ranked, rel, 1) == pytest.approx(1 / 3)


def test_recall_no_relevant_is_zero():
    assert metrics.recall_at_k(["a"], set(), 5) == 0.0


def test_reciprocal_rank_first_hit_position():
    assert metrics.reciprocal_rank(["x", "y", "a"], {"a"}) == pytest.approx(1 / 3)
    assert metrics.reciprocal_rank(["a"], {"a"}) == 1.0
    assert metrics.reciprocal_rank(["x", "y"], {"a"}) == 0.0


def test_success_at_k():
    assert metrics.success_at_k(["x", "y", "a"], {"a"}, 10) == 1.0
    assert metrics.success_at_k(["x", "y", "a"], {"a"}, 2) == 0.0   # a is at pos 3
    assert metrics.success_at_k(["a"], {"a"}, 1) == 1.0
    assert metrics.success_at_k([], {"a"}, 5) == 0.0
    assert metrics.success_at_k(["x"], set(), 5) == 0.0


def test_percentile_interpolates():
    vals = [10, 20, 30, 40]
    assert metrics.percentile(vals, 0) == 10
    assert metrics.percentile(vals, 100) == 40
    assert metrics.percentile(vals, 50) == pytest.approx(25.0)


def test_percentile_single_value():
    assert metrics.percentile([7.0], 99) == 7.0


def test_latency_summary_shape():
    s = metrics.latency_summary([5, 5, 5, 5])
    assert s["count"] == 4
    assert s["p50"] == 5 and s["p99"] == 5 and s["max"] == 5


def test_latency_summary_empty():
    s = metrics.latency_summary([])
    assert s["count"] == 0 and s["p99"] == 0.0
