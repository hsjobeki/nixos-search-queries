"""Lock the site payload builder: engine-agnostic shape + round-trip fidelity.

The published page renders purely from ``build_site_data``'s output, so its shape
is a contract. These tests stand up three deterministic fake engines (no Docker,
no network) and assert the payload is engine-count-agnostic, aligned by query id,
and that ``load_report`` inverts ``report.write_raw``.
"""
import itertools

import pytest

from searcheval.engines.base import IndexStats, SearchEngine
from searcheval.harness import evaluate
from searcheval.report import write_raw
from searcheval.schema import Doc, Query
from searcheval.site import build_site_data, load_report


class _FixedEngine(SearchEngine):
    """Deterministic fake with a configurable name (mirrors tests/test_report.py)."""

    def __init__(self, name: str):
        self.name = name
        self.docs: list[Doc] = []

    def wait_ready(self, timeout: float = 60.0) -> None:
        pass

    def reset(self) -> None:
        self.docs = []

    def index(self, docs):
        self.docs = docs
        return IndexStats(doc_count=len(docs), seconds=0.001, index_bytes=1000,
                          footprint_kind="on-disk store")

    def search(self, q, k):
        terms = q.lower().split()
        scored = []
        for d in self.docs:
            hay = f"{d.name} {d.description}".lower()
            score = sum(1 for t in terms if t in hay)
            if score:
                scored.append((score, d.id))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [doc_id for _, doc_id in scored[:k]]


def _synthetic():
    docs = [
        Doc(id="pkg:nginx", kind="package", name="nginx", description="web server"),
        Doc(id="pkg:git", kind="package", name="git",
            description="distributed version control"),
        Doc(id="opt:services.avahi.enable", kind="option",
            name="services.avahi.enable", description="whether to enable avahi daemon"),
    ]
    queries = [
        Query(id="g001", q="nginx", category="exact", relevant=frozenset({"pkg:nginx"})),
        Query(id="g002", q="git", category="exact", relevant=frozenset({"pkg:git"})),
        Query(id="g003", q="services.avahi.enable", category="dotted",
              relevant=frozenset({"opt:services.avahi.enable"})),
    ]
    return docs, queries


def _reports(names):
    docs, queries = _synthetic()
    return [evaluate(_FixedEngine(n), docs, queries, k=10, repeat=1, warmup=0)
            for n in names]


def test_engines_sorted_and_summaries_match_aggregate():
    # Deliberately unsorted input; builder must sort for stable colors/columns.
    reports = _reports(["gamma", "alpha", "beta"])
    data = build_site_data(reports)

    assert data["engines"] == ["alpha", "beta", "gamma"]
    assert set(data["summaries"]) == {"alpha", "beta", "gamma"}
    by_name = {r.engine: r for r in reports}
    for name in data["engines"]:
        assert data["summaries"][name] == by_name[name].aggregate()


def test_meta_carries_doc_count_cutoff_and_versions():
    reports = _reports(["alpha", "beta"])
    data = build_site_data(reports, versions={"alpha": "1.2.3", "beta": "9"})

    assert data["meta"]["doc_count"] == 3  # len(_synthetic docs)
    # cutoff is the max top-k actually returned; every query returns >=1 hit here.
    assert data["meta"]["cutoff"] >= 1
    assert data["meta"]["versions"] == {"alpha": "1.2.3", "beta": "9"}
    assert "generated_at" in data["meta"]


def test_queries_aligned_by_id_with_per_engine_entries():
    reports = _reports(["alpha", "beta", "gamma"])
    data = build_site_data(reports)

    assert [q["id"] for q in data["queries"]] == ["g001", "g002", "g003"]
    g001 = data["queries"][0]
    assert g001["q"] == "nginx"
    assert g001["category"] == "exact"
    assert g001["relevant"] == ["pkg:nginx"]
    assert set(g001["engines"]) == {"alpha", "beta", "gamma"}
    for eng in ("alpha", "beta", "gamma"):
        cell = g001["engines"][eng]
        assert cell["ranked"][0] == "pkg:nginx"
        for key in ("ranked", "latency_ms", "mrr", "recall@10", "success@10"):
            assert key in cell


def test_significance_has_one_entry_per_unordered_pair():
    reports = _reports(["alpha", "beta", "gamma"])
    data = build_site_data(reports)

    pairs = {(s["a"], s["b"]) for s in data["significance"]}
    expected = set(itertools.combinations(["alpha", "beta", "gamma"], 2))
    assert pairs == expected
    assert len(data["significance"]) == 3  # C(3,2)

    overall = next(r for r in data["significance"][0]["rows"] if r["group"] == "overall")
    for key in ("group", "n", "mean_diff", "lo", "hi", "significant"):
        assert key in overall
    assert overall["n"] == 3  # three paired queries


def test_single_engine_has_no_significance():
    data = build_site_data(_reports(["solo"]))
    assert data["significance"] == []
    assert data["engines"] == ["solo"]


def test_empty_reports_rejected():
    with pytest.raises(ValueError):
        build_site_data([])


def test_load_report_inverts_write_raw(tmp_path):
    [report] = _reports(["alpha"])
    path = write_raw(report, tmp_path)

    restored = load_report(path)
    assert restored.engine == report.engine
    assert restored.index_stats == report.index_stats
    assert restored.aggregate() == report.aggregate()
    # Per-query fields survive the round-trip, including the @-keyed metrics.
    assert [r.id for r in restored.results] == [r.id for r in report.results]
    assert restored.results[0].ranked == report.results[0].ranked
    assert restored.results[0].recall_at_10 == report.results[0].recall_at_10
