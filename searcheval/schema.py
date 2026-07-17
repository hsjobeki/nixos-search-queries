"""Canonical, engine-agnostic data model for corpus documents and labeled queries.

Every engine adapter indexes the exact same ``Doc`` list and answers the exact
same ``Query`` list. The engine is the only variable in the evaluation, so the
document/query representation lives here and nowhere else.

Document id conventions (stable across runs, used as relevance labels):
    packages -> ``pkg:<attr>``     e.g. ``pkg:nginx``
    options  -> ``opt:<name>``     e.g. ``opt:services.nginx.enable``
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Doc:
    """A single searchable record. ``id`` is the relevance-judgment key."""

    id: str
    kind: str  # "package" | "option"
    name: str
    description: str = ""
    extra: dict = field(default_factory=dict)  # version / type / default ...

    def flat(self) -> dict:
        """Flatten to the shape both engines index (no nested ``extra``)."""
        out = {"id": self.id, "kind": self.kind, "name": self.name,
               "description": self.description}
        for k, v in self.extra.items():
            # Never let extra shadow a core field.
            out.setdefault(k, "" if v is None else str(v))
        return out


@dataclass(frozen=True)
class Query:
    """A labeled query. ``relevant`` is the set of ``Doc.id`` that satisfy it."""

    id: str
    q: str
    category: str  # exact | prefix | typo | dotted | multiterm | intent
    relevant: frozenset[str]

    def __post_init__(self) -> None:
        if not self.relevant:
            raise ValueError(f"query {self.id!r} has no relevant judgments")


# ---------------------------------------------------------------------------
# Normalization: raw NixOS JSON -> Doc
# ---------------------------------------------------------------------------

def package_to_doc(attr: str, rec: dict) -> Doc:
    """Normalize one entry from ``packages.json`` (``rec = packages[attr]``).

    The searchable ``name`` is the **attribute path** (the dict key), not
    ``pname``. ``pname`` is neither unique nor canonical: e.g. ``nginx``,
    ``nginxStable``, ``nginxMainline`` and ``azure-cli-extensions.nginx`` all
    share ``pname == "nginx"``, which makes an exact-match query ``nginx``
    ambiguous. The attribute path is unique and is what a user types, so it is
    what search.nixos.org indexes and exact-boosts. ``pname`` is kept in
    ``extra`` for reference.
    """
    meta = rec.get("meta", {}) or {}
    desc = meta.get("description") or ""
    return Doc(
        id=f"pkg:{attr}",
        kind="package",
        name=attr,
        description=desc,
        extra={"pname": rec.get("pname", ""), "version": rec.get("version", "")},
    )


def option_to_doc(name: str, rec: dict) -> Doc:
    """Normalize one entry from ``options.json`` (top-level keyed by option name)."""
    desc = rec.get("description") or ""
    if isinstance(desc, dict):  # some options carry {_type, text}
        desc = desc.get("text", "")
    typ = rec.get("type", "")
    default = rec.get("default", "")
    if isinstance(default, dict):
        default = default.get("text", json.dumps(default))
    return Doc(
        id=f"opt:{name}",
        kind="option",
        name=name,
        description=str(desc),
        extra={"type": str(typ), "default": "" if default is None else str(default)},
    )


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_corpus(path: str | Path) -> list[Doc]:
    """Load a normalized corpus file (list of doc objects) into ``Doc`` records."""
    raw = json.loads(Path(path).read_text())
    docs = [Doc(id=d["id"], kind=d["kind"], name=d["name"],
                description=d.get("description", ""),
                extra=d.get("extra", {})) for d in raw]
    _assert_unique_ids(docs)
    return docs


def load_queries(path: str | Path) -> list[Query]:
    raw = json.loads(Path(path).read_text())
    return [Query(id=q["id"], q=q["q"], category=q["category"],
                  relevant=frozenset(q["relevant"])) for q in raw]


def validate_queries(queries: list[Query], docs: list[Doc]) -> list[str]:
    """Return human-readable problems: judgments that reference unknown doc ids.

    A golden set that points at ids not present in the corpus silently deflates
    every relevance metric, so we surface it loudly instead of scoring garbage.
    """
    known = {d.id for d in docs}
    problems: list[str] = []
    for q in queries:
        missing = sorted(q.relevant - known)
        if missing:
            problems.append(f"query {q.id!r} references unknown ids: {missing}")
    return problems


def _assert_unique_ids(docs: list[Doc]) -> None:
    seen: set[str] = set()
    for d in docs:
        if d.id in seen:
            raise ValueError(f"duplicate doc id in corpus: {d.id!r}")
        seen.add(d.id)
