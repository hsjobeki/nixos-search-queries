"""Elasticsearch adapter.

This adapter ships a deliberate, frozen, production-shaped analysis config so
the comparison measures engine capability rather than stock defaults:

  - ``name`` is analyzed by ``nixos_name``: a ``word_delimiter_graph`` filter
    splits identifiers on ``.``/``-``/underscore boundaries and on camelCase
    case-changes (``virtualHosts`` -> ``virtual``, ``hosts``), while
    ``preserve_original`` also keeps the whole path token (``services.nginx.enable``)
    so dotted queries and exact matches still hit. ``flatten_graph`` collapses the
    token graph the delimiter filter produces.
  - ``name.kw`` is a keyword sub-field for exact-match / highest-boost scoring.
  - ``name.prefix`` applies an edge-ngram filter on top of ``nixos_name`` at index
    time (search_analyzer ``nixos_name``) so leading-substring queries work.
  - ``description`` uses the built-in ``english`` analyzer for stemming.
  - ``shortness`` is a ``rank_feature`` (value ``100/len(name)``) that privileges
    short canonical names -- an explicit, tunable stand-in for BM25 fieldNorm and
    the symmetric analogue of Typesense's ``name_len`` tie-break.

``search`` sums two additive paths in a ``bool.should``: a ``dis_max`` over the
name clauses (fuzzy ``multi_match`` ``name^3``+``description``, ``name.prefix``
boost 2, exact ``name.kw`` boost 5) that win the lexical categories, PLUS a
natural-language ``match`` on ``description`` gated to >=2 query terms
(``minimum_should_match: 2``) so it is a no-op for single-token queries and only
lifts intent/multiterm; the ``shortness`` rank_feature keeps the surfaced answer
on a canonical short entry point rather than deep-option noise.

The config is frozen and documented so the comparison is reproducible and auditable.
"""

from __future__ import annotations

import json
import time

import requests

from ..schema import Doc
from .base import IndexStats, SearchEngine

INDEX = "nixos"

SETTINGS = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "filter": {
                "nixos_worddelim": {
                    "type": "word_delimiter_graph",
                    "split_on_case_change": True,
                    "generate_word_parts": True,
                    "generate_number_parts": True,
                    "catenate_words": False,
                    "catenate_all": False,
                    "preserve_original": True,
                    "split_on_numerics": False,
                    "stem_english_possessive": False,
                },
                "edge_ngram_filter": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                },
            },
            "analyzer": {
                # word_delimiter_graph splits option paths into components
                # (services.nginx.enable -> services, nginx, enable) and camelCase
                # (virtualHosts -> virtual, hosts) while preserve_original keeps the
                # whole path token; flatten_graph makes the graph safe for indexing.
                "nixos_name": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["nixos_worddelim", "lowercase", "flatten_graph"],
                },
                # Same chain plus an edge-ngram filter for leading-substring matching;
                # flatten_graph must precede edge_ngram or ES rejects the token graph.
                "nixos_prefix": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["nixos_worddelim", "lowercase", "flatten_graph", "edge_ngram_filter"],
                },
            },
        },
    },
    "mappings": {
        "properties": {
            "name": {
                "type": "text",
                "analyzer": "nixos_name",
                "fields": {
                    "kw": {"type": "keyword"},
                    "prefix": {
                        "type": "text",
                        "analyzer": "nixos_prefix",
                        "search_analyzer": "nixos_name",
                    },
                },
            },
            "description": {"type": "text", "analyzer": "english"},
            "kind": {"type": "keyword"},
            # Canonical-entry-point signal: a rank_feature holding a value that
            # is larger for shorter names (100/len). A short attr/option path
            # (`nginx`, `services.nginx.enable`) is the canonical entry point;
            # long deep-option paths and *-tray/-extras packages that merely
            # share a token are noise. BM25 fieldNorm gives this bias implicitly
            # but too weakly here, so we make it an explicit, tunable lever --
            # the symmetric analogue of Typesense's `name_len` tie-break.
            "shortness": {"type": "rank_feature"},
        }
    },
}


class Elasticsearch(SearchEngine):
    name = "elasticsearch"

    def __init__(self, url: str = "http://localhost:9200") -> None:
        self.url = url.rstrip("/")
        self.s = requests.Session()

    def wait_ready(self, timeout: float = 60.0) -> None:
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                r = self.s.get(f"{self.url}/_cluster/health", timeout=5)
                if r.ok and r.json().get("status") in ("yellow", "green"):
                    return
                last = r.text
            except requests.RequestException as e:  # not up yet
                last = str(e)
            time.sleep(1)
        raise RuntimeError(f"elasticsearch not ready at {self.url}: {last}")

    def reset(self) -> None:
        self.s.delete(f"{self.url}/{INDEX}", timeout=30)  # 404 is fine
        r = self.s.put(f"{self.url}/{INDEX}", json=SETTINGS, timeout=30)
        r.raise_for_status()

    def index(self, docs: list[Doc], batch_size: int = 2000) -> IndexStats:
        # Chunk the bulk load: a single request for a full channel (~100k docs)
        # would exceed ES's http.max_content_length (100mb default) and hold the
        # whole payload in memory. Batches keep each request bounded.
        start = time.perf_counter()
        for i in range(0, len(docs), batch_size):
            self._bulk(docs[i:i + batch_size])
        self.s.post(f"{self.url}/{INDEX}/_refresh", timeout=60).raise_for_status()
        elapsed = time.perf_counter() - start

        size = self._index_bytes()
        return IndexStats(doc_count=len(docs), seconds=elapsed, index_bytes=size,
                          footprint_kind="on-disk store")

    def _bulk(self, batch: list[Doc]) -> None:
        lines: list[str] = []
        for d in batch:
            body = d.flat()
            doc_id = body.pop("id")
            # Larger for shorter names; drives the `shortness` rank_feature.
            body["shortness"] = 100.0 / len(d.name)
            lines.append(json.dumps({"index": {"_id": doc_id}}, ensure_ascii=False))
            lines.append(json.dumps(body, ensure_ascii=False))
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        r = self.s.post(
            f"{self.url}/{INDEX}/_bulk",
            data=payload,
            headers={"Content-Type": "application/x-ndjson"},
            timeout=180,
        )
        r.raise_for_status()
        if r.json().get("errors"):
            # Surface the first item error rather than a 100kb dump.
            first = next((it for it in r.json()["items"]
                          if it.get("index", {}).get("error")), None)
            raise RuntimeError(f"elasticsearch bulk index reported errors: {first}")

    def search(self, q: str, k: int) -> list[str]:
        # Two additive scoring paths, summed by the outer bool:
        #  1. a dis_max (tie_breaker 0.3) over the name-centric clauses that win
        #     exact/prefix/typo/dotted/multiterm -- unchanged from the baseline --
        #     plus a natural-language clause: a `match` on the stemmed
        #     `description` requiring >=2 query terms (`minimum_should_match: 2`).
        #     The >=2-term gate makes it a strict no-op for single-token queries
        #     (exact/prefix/typo), so those categories cannot regress; it only
        #     fires for multi-word intent/multiterm queries, where it lifts docs
        #     whose *description* answers the query (`nginx` for "web server",
        #     `git` for "version control system") that carry no matching name.
        #  2. a `shortness` rank_feature that privileges short canonical names,
        #     so a genuine description match on a short entry point outranks the
        #     deep-option / related-package noise that shares a token. Without it
        #     the NL clause buries the very entry points it surfaces (stemming
        #     alone makes `syncthing`->`syncth` match every deep syncthing option).
        query = {
            "size": k,
            "query": {"bool": {"should": [
                {"dis_max": {
                    "tie_breaker": 0.3,
                    "queries": [
                        {"multi_match": {
                            "query": q,
                            "fields": ["name^3", "description"],
                            "fuzziness": "AUTO",
                            "prefix_length": 1,
                        }},
                        {"match": {"name.prefix": {"query": q, "boost": 2}}},
                        {"term": {"name.kw": {"value": q, "boost": 5}}},
                        {"match": {"description": {
                            "query": q, "boost": 3, "minimum_should_match": "2",
                        }}},
                    ],
                }},
                {"rank_feature": {"field": "shortness", "boost": 40}},
            ]}},
        }
        r = self.s.post(f"{self.url}/{INDEX}/_search", json=query, timeout=30)
        r.raise_for_status()
        return [h["_id"] for h in r.json()["hits"]["hits"]]

    def _index_bytes(self) -> int | None:
        try:
            r = self.s.get(f"{self.url}/{INDEX}/_stats/store", timeout=15)
            r.raise_for_status()
            return r.json()["indices"][INDEX]["total"]["store"]["size_in_bytes"]
        except (requests.RequestException, KeyError):
            return None

    def close(self) -> None:
        self.s.close()
