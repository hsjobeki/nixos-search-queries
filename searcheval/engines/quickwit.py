"""Quickwit adapter.

Quickwit is a Tantivy-based search server. Indexing uses the native ingest
endpoint; querying uses the native search endpoint with a query-language
expression (per-clause ``^`` boosts let field weighting mirror the tuned ES/TS
priority). The Elasticsearch-compatible ``_search`` endpoint is deliberately NOT
used: sorting by ``_score`` -- which Quickwit requires to opt into BM25 relevance
ranking -- 500s on ``match``/``bool`` queries over local split storage in Quickwit
0.8.x ("StorageDirectory only supports async operations"); the native endpoint's
``sort_by=_score`` is unaffected.

Deliberate, documented config. Faithful where Quickwit allows, with two honest
capability gaps vs Elasticsearch/Typesense that are reported rather than hidden:
  - No fuzzy / edit-distance query exists in Quickwit -> the ``typo`` category is
    structurally handicapped (no analogue of ES ``fuzziness`` / TS ``num_typos``).
  - No ``rank_feature`` and no score bucketing -> the short-canonical-name
    privilege relies on BM25 fieldnorms + name-clause boosts, and a weak
    ``_score,name_len`` sort tie-break (rarely fires). Weaker than ES/TS.
Minor: no camelCase splitter (like TS); no ``preserve_original`` (a separate raw
``name_raw`` field gives exact-match, the ES ``name.kw`` analogue); no numeric
``minimum_should_match`` (rely on the summed name+description match).

Two silent-failure footguns handled loudly:
  - Quickwit ignores ``_id``; we store an ``id`` field (``store_source``) and read
    it back from each hit's ``_source``.
  - Ingest reports no per-doc errors ("check the server logs"); we verify
    ``num_published_docs == len(docs)`` via ``/describe`` after indexing.
"""
from __future__ import annotations

import json
import re
import time

import requests

from ..schema import Doc
from .base import IndexStats, SearchEngine

INDEX = "nixos"
QW_VERSION = "0.8"  # MUST match the pinned quickwit image minor version (docker-compose.yml)

INDEX_CONFIG = {
    "version": QW_VERSION,
    "index_id": INDEX,
    "doc_mapping": {
        "mode": "lenient",        # dismiss any unexpected field instead of erroring
        "store_source": True,     # native search returns _source.id (Quickwit ignores _id)
        "field_mappings": [
            {"name": "id", "type": "text", "tokenizer": "raw", "stored": True},
            # default tokenizer lowercases + splits on '.'/'-'/punctuation:
            # services.nginx.enable -> services,nginx,enable (dotted category).
            {"name": "name", "type": "text", "tokenizer": "default",
             "record": "position", "fieldnorms": True},
            # raw whole-string token for exact-match boost (ES name.kw analogue).
            {"name": "name_raw", "type": "text", "tokenizer": "raw"},
            {"name": "description", "type": "text", "tokenizer": "en_stem",
             "record": "position", "fieldnorms": True},
            {"name": "kind", "type": "text", "tokenizer": "raw"},
            # weak shortness tie-break (no rank_feature available); must be fast to sort.
            {"name": "name_len", "type": "u64", "fast": True},
        ],
    },
    "search_settings": {"default_search_fields": ["name", "description"]},
}

# Split a user query into clean, lowercased alphanumeric tokens, mirroring the
# `default` tokenizer (splits on '.', '-', whitespace, punctuation). Tokens built
# this way need no query-language escaping.
_TOKEN_RE = re.compile(r"[^a-zA-Z0-9]+")


def _tokens(q: str) -> list[str]:
    return [t for t in _TOKEN_RE.split(q.lower()) if t]


def _escape_phrase(s: str) -> str:
    # Inside a quoted term only '\\' and '"' are syntactically significant.
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _build_query(q: str) -> str:
    """Compose the native query-language expression for one user query.

    Clauses are OR-ed (the native default operator is AND, so OR is explicit):
      - name/description term disjunctions, boosted 3/1 (weighted lexical + NL);
      - a prefix on the last token (boost 2) for the prefix category;
      - an exact whole-string phrase on the raw name field (boost 5).
    The exact clause quotes the whole original query so the raw-tokenized
    ``name_raw`` field matches it as one token (the ES ``name.kw`` analogue)."""
    parts: list[str] = []
    ts = _tokens(q)
    if ts:
        parts.append("(" + " OR ".join(f"name:{t}" for t in ts) + ")^3")
        parts.append("(" + " OR ".join(f"description:{t}" for t in ts) + ")^1")
        parts.append(f"(name:{ts[-1]}*)^2")
    parts.append(f'(name_raw:"{_escape_phrase(q)}")^5')
    return " OR ".join(parts)


class Quickwit(SearchEngine):
    name = "quickwit"

    def __init__(self, url: str = "http://localhost:7280") -> None:
        self.url = url.rstrip("/")
        self.s = requests.Session()

    def wait_ready(self, timeout: float = 60.0) -> None:
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                r = self.s.get(f"{self.url}/api/v1/version", timeout=5)
                if r.ok:
                    return
                last = r.text
            except requests.RequestException as e:  # not up yet
                last = str(e)
            time.sleep(1)
        raise RuntimeError(f"quickwit not ready at {self.url}: {last}")

    def reset(self) -> None:
        self.s.delete(f"{self.url}/api/v1/indexes/{INDEX}", timeout=30)  # 404 is fine
        r = self.s.post(f"{self.url}/api/v1/indexes", json=INDEX_CONFIG, timeout=30)
        r.raise_for_status()

    def index(self, docs: list[Doc], batch_size: int = 1000) -> IndexStats:
        # 10MB payload cap (much smaller than ES's 100MB) -> small batches.
        # commit=auto on all but the final batch (fast, queued), commit=force on
        # the last to flush all queued docs at once, avoiding a per-batch commit
        # that would create ~169 splits and wreck index time + footprint.
        start = time.perf_counter()
        last_start = ((len(docs) - 1) // batch_size) * batch_size if docs else 0
        for i in range(0, len(docs), batch_size):
            batch = docs[i:i + batch_size]
            payload = "\n".join(
                json.dumps({"id": d.id, "name": d.name, "name_raw": d.name,
                            "description": d.description, "kind": d.kind,
                            "name_len": len(d.name)}, ensure_ascii=False)
                for d in batch)
            commit = "force" if i == last_start else "auto"
            r = self.s.post(
                f"{self.url}/api/v1/{INDEX}/ingest",
                params={"commit": commit},
                data=payload.encode("utf-8"),
                headers={"Content-Type": "application/x-ndjson"},
                timeout=180,
            )
            r.raise_for_status()
        # Ingest reports no per-doc errors, so confirm everything published; a
        # silently dropped doc would deflate recall.
        self._await_published(len(docs), timeout=300.0)
        elapsed = time.perf_counter() - start
        return IndexStats(doc_count=len(docs), seconds=elapsed,
                          index_bytes=self._index_bytes(),
                          footprint_kind="on-disk split store")

    def _await_published(self, expected: int, timeout: float = 300.0) -> None:
        # commit=force on the final batch publishes the split, but the metastore
        # can lag a moment; poll /describe until the full count is visible.
        deadline = time.time() + timeout
        got = None
        while time.time() < deadline:
            d = self._describe()
            got = d.get("num_published_docs") if d else None
            if got is not None and got >= expected:
                return
            time.sleep(0.5)
        raise RuntimeError(f"quickwit published {got}/{expected} docs before timeout")

    def search(self, q: str, k: int) -> list[str]:
        # Native search endpoint + query-language expression. Field weighting
        # mirrors the tuned ES/TS priority via per-clause ^-boosts:
        #   name terms (^3) + description terms (^1)   -> weighted lexical + NL signal
        #   last-token prefix on name (^2)             -> prefix category
        #   exact whole-string phrase on name_raw (^5) -> exact category
        # sort_by=_score,name_len: BM25 desc then shorter name first. The tie-break
        # is weak (BM25 ties are rare), so fieldnorms + name boosts carry most of
        # the short-canonical-name privilege -- weaker than ES rank_feature / TS
        # bucketing, and reported as such.
        r = self.s.post(
            f"{self.url}/api/v1/{INDEX}/search",
            json={"query": _build_query(q), "max_hits": k, "sort_by": "_score,name_len"},
            timeout=30,
        )
        r.raise_for_status()
        return [h["_source"]["id"] for h in r.json()["hits"]]

    def _describe(self) -> dict | None:
        try:
            r = self.s.get(f"{self.url}/api/v1/indexes/{INDEX}/describe", timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            return None

    def _index_bytes(self) -> int | None:
        d = self._describe()
        if not d:
            return None
        val = d.get("size_published_splits")
        return int(val) if val is not None else None

    def close(self) -> None:
        self.s.close()
