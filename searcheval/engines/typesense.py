"""Typesense adapter.

Tuned, documented config (not near-default). The schema sets explicit
``token_separators`` (``-`` and ``.``) so dotted option paths and hyphenated
attrs tokenize by component, and enables field-level English stemming on
``description`` -- symmetric with Elasticsearch's ``english`` analyzer.

Search pins the full production lever set rather than relying on defaults, so
the config is a documented artifact even where a value equals the Typesense
default: per-field typo tolerance (``num_typos=2,1``) and prefix (``true,false``)
on name but not the stemmed description, ``split_join_tokens=fallback`` to reunite
split multi-term queries, and ``prioritize_exact_match``/``text_match_type`` pinned.

The crux lever is ``sort_by: _text_match(buckets: 4):desc, name_len:asc``: Typesense's
``text_match`` has no field-length normalization, so long deep-option paths that
share a token bury the short canonical doc. Bucketing by match score and then
ranking the shorter ``name_len`` first restores the short-canonical-name privilege
-- the deliberate analogue of Elasticsearch's BM25 fieldNorm.

One capability gap vs Elasticsearch is reported plainly rather than hidden:
Typesense has no camelCase token splitter equivalent to ES
``word_delimiter_graph``'s ``split_on_case_change``. ``infix`` search is
deliberately NOT enabled -- it would distort latency and is not equivalent to
that behavior.
"""

from __future__ import annotations

import time

import requests

from ..schema import Doc
from .base import IndexStats, SearchEngine

COLLECTION = "nixos"

SCHEMA = {
    "name": COLLECTION,
    "token_separators": ["-", "."],  # explicit dotted/hyphen path splitting so option paths tokenize by component
    "fields": [
        {"name": "name", "type": "string"},
        {"name": "description", "type": "string", "stem": True},  # v27.1 field-level English stemming (symmetric with ES english analyzer)
        {"name": "kind", "type": "string", "facet": True},
        # Short-canonical-name tie-break: Typesense's text_match has no
        # field-length normalization, so long deep-option paths that merely share
        # a token outrank the short canonical doc (pkg:postgresql,
        # opt:services.nginx.enable). name_len feeds a sort_by tie-break -- the
        # deliberate analogue of Elasticsearch's BM25 fieldNorm / rank_feature.
        {"name": "name_len", "type": "int32"},
    ],
}


class Typesense(SearchEngine):
    name = "typesense"

    def __init__(self, url: str = "http://localhost:8108",
                 api_key: str = "evalkey") -> None:
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.s.headers["X-TYPESENSE-API-KEY"] = api_key

    def wait_ready(self, timeout: float = 60.0) -> None:
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                r = self.s.get(f"{self.url}/health", timeout=5)
                if r.ok and r.json().get("ok"):
                    return
                last = r.text
            except requests.RequestException as e:
                last = str(e)
            time.sleep(1)
        raise RuntimeError(f"typesense not ready at {self.url}: {last}")

    def reset(self) -> None:
        self.s.delete(f"{self.url}/collections/{COLLECTION}", timeout=30)  # 404 ok
        r = self.s.post(f"{self.url}/collections", json=SCHEMA, timeout=30)
        r.raise_for_status()

    def index(self, docs: list[Doc], batch_size: int = 5000) -> IndexStats:
        # Chunk the import so a full channel (~100k docs) is not one multi-hundred-mb
        # request held entirely in memory. ``id`` is Typesense's native key.
        import json
        start = time.perf_counter()
        for i in range(0, len(docs), batch_size):
            batch = docs[i:i + batch_size]
            # name_len feeds the short-name sort_by tie-break (engine-local; the
            # shared Doc.flat() stays clean so Elasticsearch is unaffected).
            payload = "\n".join(
                json.dumps({**d.flat(), "name_len": len(d.name)}, ensure_ascii=False)
                for d in batch)
            r = self.s.post(
                f"{self.url}/collections/{COLLECTION}/documents/import",
                params={"action": "create"},
                data=payload.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
                timeout=180,
            )
            r.raise_for_status()
            # Import returns one JSON status object per line; any failure is fatal
            # because a partially-indexed corpus would silently skew recall.
            failures = [ln for ln in r.text.splitlines() if '"success":false' in ln]
            if failures:
                raise RuntimeError(
                    f"typesense import failed for {len(failures)} docs: {failures[:3]}")
        elapsed = time.perf_counter() - start

        return IndexStats(doc_count=len(docs), seconds=elapsed,
                          index_bytes=self._index_bytes(),
                          footprint_kind="process RSS")

    def search(self, q: str, k: int) -> list[str]:
        params = {
            "q": q,
            "query_by": "name,description",
            "query_by_weights": "3,1",
            # Per-field: typo-tolerant + prefix on the name, but NOT on the
            # stemmed description (description prefixing adds noise, not recall).
            "num_typos": "2,1",
            "prefix": "true,false",
            "typo_tokens_threshold": "1",
            "drop_tokens_threshold": "1",
            # Reunite split multi-term queries ("docker compose" <-> "dockercompose");
            # only fires on a zero-result query, so it is free on the common path.
            "split_join_tokens": "fallback",
            # Pin the exact-match privilege and scorer explicitly (both defaults in
            # v27.1) so the config is a documented artifact, not an inherited value.
            "prioritize_exact_match": "true",
            "text_match_type": "max_score",
            # Short-canonical-name privilege: bucket by text-match score (4 buckets
            # preserve real match-quality gaps) then, within a bucket, rank the
            # shorter name first -- so pkg:postgresql / opt:services.nginx.enable
            # rise above the long deep-option paths that share a token. This is the
            # deliberate analogue of Elasticsearch's BM25 fieldNorm / rank_feature.
            "sort_by": "_text_match(buckets: 4):desc, name_len:asc",
            "per_page": k,
        }
        r = self.s.get(
            f"{self.url}/collections/{COLLECTION}/documents/search",
            params=params, timeout=30,
        )
        r.raise_for_status()
        return [h["document"]["id"] for h in r.json().get("hits", [])]

    def _index_bytes(self) -> int | None:
        # Typesense is an in-RAM engine, so there is no on-disk index-size
        # analogue to Elasticsearch's store size. Report the server process's
        # resident set (RSS) as its footprint -- NOT system_memory_used_bytes,
        # which is whole-host RAM and would wildly overstate it.
        try:
            r = self.s.get(f"{self.url}/metrics.json", timeout=15)
            r.raise_for_status()
            val = r.json().get("typesense_memory_resident_bytes")
            return int(val) if val is not None else None
        except (requests.RequestException, ValueError):
            return None

    def close(self) -> None:
        self.s.close()
