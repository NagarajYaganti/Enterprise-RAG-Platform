from core.models import RetrievalFilters
from retrieval.filters import to_search_kwargs


def test_to_search_kwargs_all_unconstrained_by_default() -> None:
    kwargs = to_search_kwargs(RetrievalFilters())

    assert kwargs == {
        "language": None,
        "doc_type": None,
        "department": None,
        "date_from": None,
        "date_to": None,
    }


def test_to_search_kwargs_carries_through_each_provided_value() -> None:
    filters = RetrievalFilters(
        language="en",
        doc_type="policy",
        department="lending",
        date_from="2026-01-01",
        date_to="2026-12-31",
    )

    kwargs = to_search_kwargs(filters)

    assert kwargs == {
        "language": "en",
        "doc_type": "policy",
        "department": "lending",
        "date_from": "2026-01-01",
        "date_to": "2026-12-31",
    }
