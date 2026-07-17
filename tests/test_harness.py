"""End-to-end wiring tests: corpus -> engine -> harness -> report.

Uses an in-process fake engine (a trivial substring matcher) over a small
synthetic corpus purely to exercise the orchestration/scoring/report code paths.
It is NOT a stand-in for the real Elasticsearch/Typesense comparison -- it only
proves the harness plumbing is sound so that, when pointed at real engines over
the full corpus, the numbers are computed correctly. (Running SubstringEngine
over the 168k-doc full corpus would be far too slow for a unit test.)
"""

import json

from searcheval.engines.base import IndexStats, SearchEngine
from searcheval.harness import evaluate
from searcheval.report import write_matrix, write_raw
from searcheval.schema import Doc, Query


class SubstringEngine(SearchEngine):
    """Ranks docs by naive token overlap between query and name/description."""

    name = "fake"

    def __init__(self):
        self.docs = []

    def wait_ready(self, timeout: float = 60.0) -> None:
        pass

    def reset(self) -> None:
        self.docs = []

    def index(self, docs):
        self.docs = docs
        return IndexStats(doc_count=len(docs), seconds=0.001, index_bytes=1234,
                          footprint_kind="on-disk store")

    def search(self, q, k):
        terms = q.lower().split()
        scored = []
        for d in self.docs:
            hay = f"{d.name} {d.description}".lower()
            score = sum(1 for t in terms if t in hay)
            # prefix credit so "postgres" ranks postgresql
            score += sum(0.5 for t in terms if t in d.name.lower())
            if score:
                scored.append((score, d.id))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [doc_id for _, doc_id in scored[:k]]


def _synthetic() -> tuple[list[Doc], list[Query]]:
    """A tiny corpus whose exact-name queries have a single unambiguous target,
    so a substring matcher must rank that target first if scoring is wired to the
    right ids. Names are chosen to avoid cross-query substring collisions."""
    docs = [
        Doc(id="pkg:nginx", kind="package", name="nginx", description="web server"),
        Doc(id="pkg:postgresql", kind="package", name="postgresql",
            description="relational database"),
        Doc(id="pkg:htop", kind="package", name="htop",
            description="interactive process viewer"),
        Doc(id="pkg:redis", kind="package", name="redis",
            description="in memory data store"),
        Doc(id="pkg:git", kind="package", name="git",
            description="distributed version control"),
        Doc(id="opt:services.avahi.enable", kind="option",
            name="services.avahi.enable", description="whether to enable avahi daemon"),
    ]
    queries = [
        Query(id="g001", q="nginx", category="exact", relevant=frozenset({"pkg:nginx"})),
        Query(id="g002", q="postgresql", category="exact",
              relevant=frozenset({"pkg:postgresql"})),
        Query(id="g003", q="htop", category="exact", relevant=frozenset({"pkg:htop"})),
        Query(id="g004", q="web server", category="intent",
              relevant=frozenset({"pkg:nginx"})),
        Query(id="g005", q="services.avahi.enable", category="dotted",
              relevant=frozenset({"opt:services.avahi.enable"})),
    ]
    return docs, queries


def test_full_pipeline(tmp_path):
    docs, queries = _synthetic()

    rep = evaluate(SubstringEngine(), docs, queries, k=10, repeat=2, warmup=1)
    assert len(rep.results) == len(queries)

    agg = rep.aggregate()
    # Sanity: only the known-item aggregate keys are present and in range.
    for m in ("success@10", "mrr", "recall@10"):
        assert 0.0 <= agg[m] <= 1.0
    # Precision / nDCG are removed by design; they must not reappear.
    assert "p@1" not in agg and "p@5" not in agg and "ndcg@10" not in agg
    assert agg["latency"]["count"] == len(queries)
    assert set(agg["by_category"]) == {"exact", "intent", "dotted"}

    # A substring matcher must nail exact-name queries: the doc whose name IS the
    # query is the only match, so it surfaces at rank 1 and exact-category MRR is
    # 1.0. This proves scoring is wired to the right ids, independent of engine
    # quality.
    assert agg["by_category"]["exact"]["mrr"] > 0.9

    raw = write_raw(rep, tmp_path)
    matrix = write_matrix([rep], tmp_path)

    dumped = json.loads(raw.read_text())
    assert dumped["engine"] == "fake"
    assert len(dumped["per_query"]) == len(queries)
    assert "perf" not in dumped
    assert dumped["summary"]["index"]["doc_count"] == len(docs)
    row = dumped["per_query"][0]
    assert set(row) >= {"id", "q", "category", "latency_ms", "ranked",
                        "relevant", "recall@10", "mrr", "success@10"}
    assert "p@1" not in row and "p@5" not in row and "ndcg@10" not in row

    md = matrix.read_text()
    assert "# Search backend evaluation" in md
    assert "Success@10 by query category" in md
    # Latency + indexing are always present now: a single corpus yields both.
    assert "## Latency, ms" in md
    assert "## Indexing" in md
    # The header must state the known-item rationale so a reader never mistakes
    # the omitted Precision/nDCG for an oversight.
    assert "known-item metrics" in md
    assert "not interchangeable" not in md
