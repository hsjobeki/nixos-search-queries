"""Validity + completeness guards for the committed 150-query judged set.

The whole benchmark's relevance numbers are only trustworthy if the judged set
is internally consistent against the full corpus it is scored on: every relevant
id must exist, every category must be present and balanced, and no two queries
may share a query string (a duplicate would double-count one axis). Known-item
validity (Success@10, MRR, Recall@10) needs only that each query's canonical
entry points (packages + `.enable` options) are labeled and present, which the
authors verified by hand; here we lock the mechanical invariants that a future
edit could break.
"""

from collections import Counter
from pathlib import Path

import pytest

from searcheval.schema import load_corpus, load_queries, validate_queries

# corpus/full.json is a large fetched artifact (gitignored, reproduced via
# scripts/fetch_corpus.py). When it is absent -- e.g. the hermetic Nix package
# build sees only git-tracked files -- these full-corpus checks skip rather than
# fail; they still run in dev/CI where the corpus has been fetched.
pytestmark = pytest.mark.skipif(
    not Path("corpus/full.json").exists(),
    reason="corpus/full.json not present; run scripts/fetch_corpus.py")

CATEGORIES = {"exact", "prefix", "typo", "dotted", "multiterm", "intent"}


def _load():
    return load_corpus("corpus/full.json"), load_queries("queries/queries.json")


def test_all_relevant_ids_exist_in_full_corpus():
    docs, queries = _load()
    assert validate_queries(queries, docs) == []


def test_exactly_six_categories_each_balanced():
    _, queries = _load()
    counts = Counter(q.category for q in queries)
    assert set(counts) == CATEGORIES
    # Balanced set: 25 per category, 150 total. Kept exact so an accidental
    # drop/dupe during a future edit is caught rather than silently skewing
    # per-category aggregates.
    assert all(n == 25 for n in counts.values()), counts
    assert sum(counts.values()) == 150


def test_no_duplicate_query_strings():
    _, queries = _load()
    strings = [q.q for q in queries]
    dupes = [s for s, n in Counter(strings).items() if n > 1]
    assert not dupes, dupes


def test_every_query_has_relevant_judgments():
    _, queries = _load()
    # Query.__post_init__ already rejects empty sets on load; assert the loaded
    # set upholds it so the invariant is covered by an explicit test too.
    assert all(len(q.relevant) >= 1 for q in queries)


def test_query_ids_are_unique_and_sequential():
    _, queries = _load()
    ids = [q.id for q in queries]
    assert len(set(ids)) == len(ids)
    assert ids == [f"g{i:03d}" for i in range(1, len(queries) + 1)]
