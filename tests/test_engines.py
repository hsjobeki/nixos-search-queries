"""Offline engine-registry + Quickwit config/query tests (no Docker, no network).

Instantiating an adapter only opens a ``requests.Session``; it makes no network
call until ``wait_ready``/``reset``/``index``/``search``. These tests exercise
the registry contract and the Quickwit config/query shapes without a live server,
so a config typo or a broken id-extraction path fails in CI, not only in a live run.
"""
import json

from searcheval.engines import ENGINES, Quickwit
from searcheval.engines.quickwit import INDEX, INDEX_CONFIG, QW_VERSION, _build_query


def test_registry_is_the_three_engines():
    assert set(ENGINES) == {"elasticsearch", "typesense", "quickwit"}


def test_registry_names_match_keys():
    # The registry key IS the --engine CLI value and MUST equal the class .name.
    for key, cls in ENGINES.items():
        assert cls.name == key


def test_quickwit_defaults():
    qw = Quickwit()
    assert qw.name == "quickwit"
    assert qw.url == "http://localhost:7280"
    qw.close()


def test_quickwit_url_is_stripped():
    assert Quickwit(url="http://host:7280/").url == "http://host:7280"


def test_index_config_is_serializable_and_well_formed():
    dumped = json.loads(json.dumps(INDEX_CONFIG))
    assert dumped["index_id"] == INDEX
    # The config version must track the pinned image minor (kept in sync by hand).
    assert dumped["version"] == QW_VERSION
    fields = {f["name"]: f for f in dumped["doc_mapping"]["field_mappings"]}
    assert {"id", "name", "name_raw", "description", "kind", "name_len"} <= set(fields)
    # id is read back from _source (Quickwit ignores _id), so source must be stored.
    assert dumped["doc_mapping"]["store_source"] is True
    # name_len feeds the sort tie-break, so it MUST be a fast field.
    assert fields["name_len"]["fast"] is True
    # name/description carry BM25 -> fieldnorms required for _score sorting.
    assert fields["name"]["fieldnorms"] is True
    assert fields["description"]["fieldnorms"] is True


class _CannedResponse:
    def raise_for_status(self):
        pass

    def json(self):
        # Native search response: a top-level `hits` list, each hit carrying _source.
        return {"hits": [
            {"_source": {"id": "pkg:nginx"}},
            {"_source": {"id": "opt:services.nginx.enable"}},
        ]}


class _CapturingSession:
    """Captures the body Quickwit.search POSTs; returns a canned native hit list."""

    def __init__(self):
        self.captured = None

    def post(self, url, json=None, timeout=None):
        self.captured = (url, json)
        return _CannedResponse()

    def close(self):
        pass


def test_quickwit_search_body_and_id_extraction():
    qw = Quickwit()
    session = _CapturingSession()
    qw.s = session  # no network: capture the request instead

    ids = qw.search("nginx", 10)
    # Ids come from _source.id, in hit order.
    assert ids == ["pkg:nginx", "opt:services.nginx.enable"]

    url, body = session.captured
    assert url.endswith(f"/api/v1/{INDEX}/search")
    # The body must be valid JSON (requests would serialize it) and carry the levers.
    json.loads(json.dumps(body))
    assert body["max_hits"] == 10
    # BM25 desc then shorter name first; native sort_by is a comma-separated string.
    assert body["sort_by"] == "_score,name_len"
    # The query is a native query-language expression, not an ES DSL object.
    assert isinstance(body["query"], str)


def test_build_query_structure():
    qs = _build_query("services.openssh.enable")
    # Tokenized to clean lowercase terms, OR-ed with per-field boosts.
    assert "(name:services OR name:openssh OR name:enable)^3" in qs
    assert "(description:services OR description:openssh OR description:enable)^1" in qs
    # Prefix on the last token (prefix category) and the exact whole-string phrase.
    assert "(name:enable*)^2" in qs
    assert '(name_raw:"services.openssh.enable")^5' in qs
    # Top-level clauses are OR-ed (native default operator is AND).
    assert " OR " in qs


def test_build_query_escapes_quotes_in_exact_phrase():
    # A stray quote in the raw phrase must be escaped so the expression stays valid.
    qs = _build_query('foo"bar')
    assert '(name_raw:"foo\\"bar")^5' in qs


def test_build_query_handles_no_alnum_tokens():
    # A query with no alphanumeric tokens still yields a valid exact-phrase clause
    # and no empty name/description disjunctions.
    qs = _build_query("...")
    assert qs == '(name_raw:"...")^5'
