import re

from core.models import Chunk
from core.prompt_registry import REFUSAL_TEXT
from pydantic import BaseModel

# Prompt-instructed [chunk_id] markers (see config/prompts/*/retrieval-qa.yaml),
# validated post-hoc against the retrieved set. Deliberately NOT Anthropic's
# native TextBlock.citations feature, to stay vendor-neutral across providers
# (Plan v2 §A.9) — every LLMProvider adapter must be able to produce citations
# this way, not just Anthropic's.
_CITATION_PATTERN = re.compile(r"\[([A-Za-z0-9_\-:.]+)\]")


class CitationCheckResult(BaseModel):
    cited_chunk_ids: list[str]
    valid_chunk_ids: list[str]
    hallucinated_chunk_ids: list[str]
    is_refusal: bool
    is_grounded: bool


def extract_cited_chunk_ids(text: str) -> list[str]:
    seen: list[str] = []
    for match in _CITATION_PATTERN.finditer(text):
        chunk_id = match.group(1)
        if chunk_id not in seen:
            seen.append(chunk_id)
    return seen


def check_citations(text: str, retrieved_chunks: list[Chunk]) -> CitationCheckResult:
    """GAP-MATRIX's primary hallucination control: an answer is "grounded"
    only if it's the exact refusal sentence, or every [chunk_id] marker it
    cites resolves to a chunk that was actually retrieved for this query.
    An answer with zero citations that ISN'T the refusal sentence is
    ungrounded (the model answered without pointing at any source) — callers
    should treat is_grounded=False as a signal to fall back to the refusal
    text, not to trust the answer as-is.
    """
    is_refusal = text.strip() == REFUSAL_TEXT
    cited = extract_cited_chunk_ids(text)
    available_ids = {chunk.id for chunk in retrieved_chunks}

    valid = [chunk_id for chunk_id in cited if chunk_id in available_ids]
    hallucinated = [chunk_id for chunk_id in cited if chunk_id not in available_ids]

    is_grounded = is_refusal or (bool(valid) and not hallucinated)

    return CitationCheckResult(
        cited_chunk_ids=cited,
        valid_chunk_ids=valid,
        hallucinated_chunk_ids=hallucinated,
        is_refusal=is_refusal,
        is_grounded=is_grounded,
    )
