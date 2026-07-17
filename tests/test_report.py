"""Report rendering: the significance section must scale past two engines.

With three engines the significance section emits one paired-bootstrap block per
unordered pair (a-b, a-c, b-c) under a single header. This guards the N-engine
generalization: the old code silently dropped significance whenever len != 2.
"""
from searcheval.engines.base import IndexStats, SearchEngine
from searcheval.harness import evaluate
from searcheval.report import write_matrix
from searcheval.schema import Doc, Query


class _FixedEngine(SearchEngine):
    """A deterministic fake whose name is configurable, so we can stand up three
    distinct engine reports without any network or Docker."""

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


def test_three_engine_significance_has_one_block_per_pair(tmp_path):
    docs, queries = _synthetic()
    reports = [evaluate(_FixedEngine(name), docs, queries, k=10, repeat=1, warmup=0)
               for name in ("alpha", "beta", "gamma")]

    md = write_matrix(reports, tmp_path).read_text()

    # Single section header, three pairwise sub-blocks (3 choose 2).
    assert "## Significance: paired MRR by engine pair" in md
    dash = "\u2212"
    assert f"### alpha {dash} beta" in md
    assert f"### alpha {dash} gamma" in md
    assert f"### beta {dash} gamma" in md
    # All three engines appear as columns in the relevance/latency/indexing tables.
    for name in ("alpha", "beta", "gamma"):
        assert name in md


def test_single_engine_has_no_significance_section(tmp_path):
    docs, queries = _synthetic()
    rep = evaluate(_FixedEngine("solo"), docs, queries, k=10, repeat=1, warmup=0)
    md = write_matrix([rep], tmp_path).read_text()
    # Significance needs a pair; with one engine the section is omitted entirely.
    assert "## Significance" not in md
