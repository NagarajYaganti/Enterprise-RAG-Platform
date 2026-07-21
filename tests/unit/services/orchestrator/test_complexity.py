from orchestrator.complexity import assess_complexity


def test_short_single_question_is_simple() -> None:
    result = assess_complexity("What is the loan review deadline?", sub_questions=[])
    assert result == "simple"


def test_multiple_sub_questions_is_complex() -> None:
    result = assess_complexity(
        "What is the loan review deadline and what is the refund policy?",
        sub_questions=[
            "What is the loan review deadline?",
            "What is the refund policy?",
        ],
    )
    assert result == "complex"


def test_single_sub_question_is_not_by_itself_complex() -> None:
    result = assess_complexity(
        "What is the loan review deadline?",
        sub_questions=["What is the loan review deadline?"],
    )
    assert result == "simple"


def test_long_query_is_complex() -> None:
    long_query = "What is the deadline? " * 20  # well over 200 chars
    assert len(long_query) > 200
    result = assess_complexity(long_query, sub_questions=[])
    assert result == "complex"


def test_custom_length_threshold_is_respected() -> None:
    query = "a" * 50
    assert assess_complexity(query, sub_questions=[], length_threshold=100) == "simple"
    assert assess_complexity(query, sub_questions=[], length_threshold=10) == "complex"


def test_boundary_exactly_at_threshold_is_simple() -> None:
    query = "a" * 200
    assert assess_complexity(query, sub_questions=[], length_threshold=200) == "simple"


def test_boundary_one_over_threshold_is_complex() -> None:
    query = "a" * 201
    assert assess_complexity(query, sub_questions=[], length_threshold=200) == "complex"
