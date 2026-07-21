from collections.abc import Generator

import pytest
from connectors.keyword.opensearch_index import (
    ANALYZERS,
    LANGUAGE_TO_ANALYZER,
    OpenSearchIndex,
    ensure_index,
)
from connectors.vectorstores.errors import TenantMismatchError
from core.models import Chunk
from opensearchpy import OpenSearch

INDEX_NAME = "test_opensearch_index"


@pytest.fixture()
def client() -> Generator[OpenSearch, None, None]:
    c = OpenSearch(hosts=[{"host": "localhost", "port": 9200}], use_ssl=False, verify_certs=False)
    c.indices.delete(index=f"{INDEX_NAME}_*", ignore=[404])
    ensure_index(c, INDEX_NAME)
    yield c
    c.indices.delete(index=f"{INDEX_NAME}_*", ignore=[404])


def _chunk(
    tenant_id: str,
    chunk_id: str,
    text: str,
    principals: list[str],
    language: str = "en",
    doc_type: str | None = None,
    department: str | None = None,
    date: str | None = None,
    search_analyzer: str | None = None,
) -> Chunk:
    return Chunk(
        id=chunk_id,
        tenant_id=tenant_id,
        document_id=f"doc-{chunk_id}",
        text=text,
        position=0,
        language=language,
        version=1,
        acl_principals=principals,
        doc_type=doc_type,
        department=department,
        date=date,
        # Defaults to LANGUAGE_TO_ANALYZER's real mapping for `language` so
        # existing language-filtered tests land in the index their filter
        # actually targets; explicit search_analyzer overrides this for
        # tests that need a mismatch or an unmapped language.
        search_analyzer=search_analyzer or LANGUAGE_TO_ANALYZER.get(language, "standard"),
    )


def test_ensure_index_creates_one_real_index_per_analyzer(client: OpenSearch) -> None:
    for analyzer in ANALYZERS:
        assert client.indices.exists(index=f"{INDEX_NAME}_{analyzer}")


def test_ensure_index_maps_tenant_id_as_keyword(client: OpenSearch) -> None:
    real_index = f"{INDEX_NAME}_english"
    mapping = client.indices.get_mapping(index=real_index)
    props = mapping[real_index]["mappings"]["properties"]
    assert props["tenant_id"]["type"] == "keyword"
    assert props["acl_principals"]["type"] == "keyword"
    assert props["document_id"]["type"] == "keyword"
    assert props["text"]["type"] == "text"


def test_ensure_index_maps_phase3_filter_fields_explicitly(client: OpenSearch) -> None:
    real_index = f"{INDEX_NAME}_english"
    mapping = client.indices.get_mapping(index=real_index)
    props = mapping[real_index]["mappings"]["properties"]
    assert props["language"]["type"] == "keyword"
    assert props["doc_type"]["type"] == "keyword"
    assert props["department"]["type"] == "keyword"
    assert props["date"]["type"] == "date"


def test_ensure_index_applies_the_correct_analyzer_per_language_index(client: OpenSearch) -> None:
    for analyzer in ("arabic", "cjk", "hindi", "standard"):
        real_index = f"{INDEX_NAME}_{analyzer}"
        mapping = client.indices.get_mapping(index=real_index)
        assert mapping[real_index]["mappings"]["properties"]["text"]["analyzer"] == analyzer


def test_upsert_rejects_chunk_from_a_different_tenant(client: OpenSearch) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    bad_chunk = _chunk("tenant-b", "c1", "hello world", ["p1"])

    with pytest.raises(TenantMismatchError):
        index.upsert("tenant-a", [bad_chunk])


def test_search_is_tenant_isolated(client: OpenSearch) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert("tenant-a", [_chunk("tenant-a", "c1", "quarterly earnings report", ["p1"])])
    index.upsert("tenant-b", [_chunk("tenant-b", "c2", "quarterly earnings summary", ["p1"])])

    hits = index.search("tenant-a", "quarterly earnings", principals=["p1"], top_k=10)

    assert [h.chunk_id for h in hits] == ["c1"]


def test_search_prefilters_on_acl_principals(client: OpenSearch) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert(
        "tenant-a",
        [
            _chunk("tenant-a", "c3", "quarterly earnings report", ["p1"]),
            _chunk("tenant-a", "c4", "quarterly earnings forecast", ["p9"]),
        ],
    )

    hits = index.search("tenant-a", "quarterly earnings", principals=["p1"], top_k=10)

    assert {h.chunk_id for h in hits} == {"c3"}


def test_delete_removes_only_the_target_document(client: OpenSearch) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert(
        "tenant-a",
        [
            _chunk("tenant-a", "c5", "alpha report text", ["p1"]),
            _chunk("tenant-a", "c6", "beta report text", ["p1"]),
        ],
    )

    index.delete("tenant-a", "doc-c5")

    remaining = index.search("tenant-a", "report", principals=["p1"], top_k=10)
    assert {h.chunk_id for h in remaining} == {"c6"}


def test_delete_is_tenant_scoped(client: OpenSearch) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert("tenant-a", [_chunk("tenant-a", "c7", "gamma report text", ["p1"])])
    index.upsert("tenant-b", [_chunk("tenant-b", "c7dup", "gamma report text", ["p1"])])

    index.delete("tenant-b", "doc-c7dup")

    remaining_a = index.search("tenant-a", "gamma", principals=["p1"], top_k=10)
    assert {h.chunk_id for h in remaining_a} == {"c7"}


def test_search_with_no_filters_is_unconstrained_on_metadata(client: OpenSearch) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert(
        "tenant-a",
        [
            _chunk("tenant-a", "c8", "quarterly report alpha", ["p1"], doc_type="policy"),
            _chunk("tenant-a", "c9", "quarterly report beta", ["p1"], doc_type="report"),
        ],
    )

    hits = index.search("tenant-a", "quarterly report", principals=["p1"], top_k=10)

    assert {h.chunk_id for h in hits} == {"c8", "c9"}


def test_search_doc_type_filter_excludes_non_matching(client: OpenSearch) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert(
        "tenant-a",
        [
            _chunk("tenant-a", "c10", "quarterly report alpha", ["p1"], doc_type="policy"),
            _chunk("tenant-a", "c11", "quarterly report beta", ["p1"], doc_type="report"),
        ],
    )

    hits = index.search(
        "tenant-a", "quarterly report", principals=["p1"], top_k=10, doc_type="policy"
    )

    assert {h.chunk_id for h in hits} == {"c10"}


def test_search_department_filter_excludes_non_matching(client: OpenSearch) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert(
        "tenant-a",
        [
            _chunk("tenant-a", "c12", "quarterly report alpha", ["p1"], department="lending"),
            _chunk("tenant-a", "c13", "quarterly report beta", ["p1"], department="claims"),
        ],
    )

    hits = index.search(
        "tenant-a", "quarterly report", principals=["p1"], top_k=10, department="lending"
    )

    assert {h.chunk_id for h in hits} == {"c12"}


def test_search_language_filter_excludes_non_matching(client: OpenSearch) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert(
        "tenant-a",
        [
            _chunk("tenant-a", "c14", "quarterly report alpha", ["p1"], language="en"),
            _chunk("tenant-a", "c15", "quarterly report beta", ["p1"], language="es"),
        ],
    )

    hits = index.search(
        "tenant-a", "quarterly report", principals=["p1"], top_k=10, language="en"
    )

    assert {h.chunk_id for h in hits} == {"c14"}


def test_search_date_range_filter_excludes_out_of_range(client: OpenSearch) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert(
        "tenant-a",
        [
            _chunk("tenant-a", "c16", "quarterly report alpha", ["p1"], date="2026-01-01"),
            _chunk("tenant-a", "c17", "quarterly report beta", ["p1"], date="2026-06-01"),
            _chunk("tenant-a", "c18", "quarterly report gamma", ["p1"], date="2026-12-01"),
        ],
    )

    hits = index.search(
        "tenant-a",
        "quarterly report",
        principals=["p1"],
        top_k=10,
        date_from="2026-05-01",
        date_to="2026-11-01",
    )

    assert {h.chunk_id for h in hits} == {"c17"}


def test_upsert_routes_different_languages_to_different_real_indices(
    client: OpenSearch,
) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert(
        "tenant-a",
        [
            _chunk("tenant-a", "c21", "hello world", ["p1"], language="en"),
            _chunk("tenant-a", "c22", "مرحبا بالعالم", ["p1"], language="ar"),
        ],
    )

    english_doc = client.get(index=f"{INDEX_NAME}_english", id="c21")
    arabic_doc = client.get(index=f"{INDEX_NAME}_arabic", id="c22")
    assert english_doc["_source"]["chunk_id"] == "c21"
    assert arabic_doc["_source"]["chunk_id"] == "c22"


def test_search_with_no_language_filter_finds_results_across_multiple_language_indices(
    client: OpenSearch,
) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert(
        "tenant-a",
        [
            _chunk("tenant-a", "c23", "quarterly compliance policy", ["p1"], language="en"),
            _chunk("tenant-a", "c24", "quarterly compliance policy", ["p1"], language="ar"),
        ],
    )

    hits = index.search("tenant-a", "quarterly compliance", principals=["p1"], top_k=10)

    assert {h.chunk_id for h in hits} == {"c23", "c24"}


def test_search_with_explicit_language_filter_only_hits_that_one_index(
    client: OpenSearch,
) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert(
        "tenant-a",
        [
            _chunk("tenant-a", "c25", "quarterly compliance policy", ["p1"], language="en"),
            _chunk("tenant-a", "c26", "quarterly compliance policy", ["p1"], language="ar"),
        ],
    )

    hits = index.search(
        "tenant-a", "quarterly compliance", principals=["p1"], top_k=10, language="en"
    )

    assert {h.chunk_id for h in hits} == {"c25"}


def test_delete_removes_a_document_regardless_of_which_language_index_its_chunks_are_in(
    client: OpenSearch,
) -> None:
    # A mixed-language document (Phase 1's per-section detection): its
    # chunks can live in TWO different real indices at once.
    index = OpenSearchIndex(client, INDEX_NAME)
    english_chunk = _chunk("tenant-a", "c27", "english section text", ["p1"], language="en")
    arabic_chunk = _chunk("tenant-a", "c28", "arabic section text", ["p1"], language="ar")
    mixed_doc_id = "doc-mixed"
    english_chunk.document_id = mixed_doc_id
    arabic_chunk.document_id = mixed_doc_id
    index.upsert("tenant-a", [english_chunk, arabic_chunk])

    index.delete("tenant-a", mixed_doc_id)

    remaining = index.search("tenant-a", "section text", principals=["p1"], top_k=10)
    assert remaining == []


def test_search_filter_excludes_chunks_missing_the_field(client: OpenSearch) -> None:
    index = OpenSearchIndex(client, INDEX_NAME)
    index.upsert(
        "tenant-a",
        [
            _chunk("tenant-a", "c19", "quarterly report alpha", ["p1"], doc_type="policy"),
            _chunk("tenant-a", "c20", "quarterly report beta", ["p1"], doc_type=None),
        ],
    )

    hits = index.search(
        "tenant-a", "quarterly report", principals=["p1"], top_k=10, doc_type="policy"
    )

    assert {h.chunk_id for h in hits} == {"c19"}
