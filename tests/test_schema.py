"""Schema/normalization tests. A wrong id or dropped field here corrupts every
relevance judgment downstream, so these pin the contract precisely.
"""

import json
from pathlib import Path

import pytest

from searcheval import schema
from searcheval.schema import (Doc, Query, load_corpus, load_queries,
                               option_to_doc, package_to_doc, validate_queries)


def test_package_name_is_attr_not_pname():
    # Attribute path is the searchable name; pname (non-unique) goes to extra.
    doc = package_to_doc("nginxStable", {"pname": "nginx", "version": "1.26",
                                         "meta": {"description": "web server"}})
    assert doc.id == "pkg:nginxStable"
    assert doc.kind == "package"
    assert doc.name == "nginxStable"          # attr, NOT pname
    assert doc.extra["pname"] == "nginx"
    assert doc.description == "web server"
    assert doc.extra["version"] == "1.26"


def test_namespaced_attr_preserved_as_name():
    # The collision case that motivated the change: shares pname 'nginx'.
    doc = package_to_doc("azure-cli-extensions.nginx", {"pname": "nginx"})
    assert doc.name == "azure-cli-extensions.nginx"
    assert doc.id == "pkg:azure-cli-extensions.nginx"


def test_package_missing_meta_defaults_empty_description():
    doc = package_to_doc("foo", {})
    assert doc.description == ""
    assert doc.name == "foo"                  # name is always the attr


def test_option_normalization_and_dict_default():
    doc = option_to_doc("services.nginx.enable", {
        "description": "Whether to enable Nginx.",
        "type": "boolean",
        "default": {"_type": "literalExpression", "text": "false"},
    })
    assert doc.id == "opt:services.nginx.enable"
    assert doc.kind == "option"
    assert doc.extra["default"] == "false"
    assert doc.extra["type"] == "boolean"


def test_option_dict_description_uses_text():
    doc = option_to_doc("x", {"description": {"_type": "mdDoc", "text": "hello"}})
    assert doc.description == "hello"


def test_flat_never_shadows_core_fields():
    doc = Doc(id="pkg:x", kind="package", name="x", description="d",
              extra={"name": "SHOULD_NOT_WIN", "version": "1"})
    flat = doc.flat()
    assert flat["name"] == "x"  # core field wins over extra
    assert flat["version"] == "1"


def test_flat_stringifies_none_extra():
    doc = Doc(id="opt:x", kind="option", name="x", extra={"default": None})
    assert doc.flat()["default"] == ""


def test_query_requires_relevant():
    with pytest.raises(ValueError):
        Query(id="q", q="x", category="exact", relevant=frozenset())


def test_validate_queries_flags_unknown_ids():
    docs = [Doc(id="pkg:a", kind="package", name="a")]
    queries = [Query(id="q1", q="a", category="exact",
                     relevant=frozenset({"pkg:a", "pkg:missing"}))]
    problems = validate_queries(queries, docs)
    assert len(problems) == 1
    assert "pkg:missing" in problems[0]


def test_load_roundtrip(tmp_path):
    corpus = [{"id": "pkg:a", "kind": "package", "name": "a",
               "description": "d", "extra": {"version": "1"}}]
    qs = [{"id": "q1", "q": "a", "category": "exact", "relevant": ["pkg:a"]}]
    cpath = tmp_path / "c.json"
    qpath = tmp_path / "q.json"
    cpath.write_text(json.dumps(corpus))
    qpath.write_text(json.dumps(qs))
    docs = load_corpus(cpath)
    queries = load_queries(qpath)
    assert docs[0].id == "pkg:a"
    assert queries[0].relevant == frozenset({"pkg:a"})
    assert validate_queries(queries, docs) == []


def test_duplicate_ids_rejected(tmp_path):
    corpus = [{"id": "pkg:a", "kind": "package", "name": "a"},
              {"id": "pkg:a", "kind": "package", "name": "a2"}]
    p = tmp_path / "c.json"
    p.write_text(json.dumps(corpus))
    with pytest.raises(ValueError):
        load_corpus(p)


@pytest.mark.skipif(
    not Path("corpus/full.json").exists(),
    reason="corpus/full.json is a gitignored fetched artifact; "
           "run scripts/fetch_corpus.py to enable this check")
def test_committed_full_and_queries_are_consistent():
    """The shipped full corpus + hand-judged query set must validate clean."""
    docs = load_corpus("corpus/full.json")
    queries = load_queries("queries/queries.json")
    assert validate_queries(queries, docs) == []
    assert len(docs) >= 100000 and len(queries) == 150
