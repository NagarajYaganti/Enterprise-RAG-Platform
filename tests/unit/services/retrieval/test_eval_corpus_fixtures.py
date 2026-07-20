from tests.fixtures.eval_corpus.loader import load_eval_documents, load_golden_queries


def test_eval_corpus_has_at_least_twenty_documents() -> None:
    documents = load_eval_documents()
    assert len(documents) >= 20


def test_eval_corpus_document_ids_are_unique() -> None:
    documents = load_eval_documents()
    ids = [doc["id"] for doc in documents]
    assert len(ids) == len(set(ids))


def test_golden_queries_reference_only_real_document_ids() -> None:
    documents = load_eval_documents()
    valid_ids = {doc["id"] for doc in documents}
    golden_queries = load_golden_queries()

    assert len(golden_queries) >= 10
    for golden_query in golden_queries:
        for chunk_id in golden_query.relevant_chunk_ids:
            assert chunk_id in valid_ids, f"{chunk_id!r} in golden query {golden_query.query!r}"


def test_every_golden_query_has_at_least_one_relevant_chunk() -> None:
    for golden_query in load_golden_queries():
        assert len(golden_query.relevant_chunk_ids) >= 1
