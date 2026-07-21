import uuid
from collections import Counter
from typing import Any

from core.interfaces import Chunker
from core.models import Chunk, ParsedDocument

HEADING_CATEGORIES = frozenset({"Title", "Header"})


class StructureAwareChunker(Chunker):
    """Chunker adapter: splits on heading/title boundaries from
    ParsedDocument.structural_elements, keeping each section (heading + the
    text under it until the next heading) as one chunk.

    Each section's language is its constituent elements' own
    `detected_language` (set by preprocessing.pipeline.run_pipeline, which
    detects language per element -- documents mix languages, so detecting
    once on the whole document hides this), weighted by each element's
    TEXT LENGTH rather than counted per-element -- a short heading
    shouldn't outvote a much longer body paragraph in a different language
    (verified empirically: an equal-weight vote let a short English heading
    tie against one long Arabic paragraph). An element missing
    `detected_language` (e.g. a caller invoking this chunker directly,
    bypassing run_pipeline) falls back to the `language` param, preserving
    prior behavior for such callers.
    """

    def chunk(
        self, doc: ParsedDocument, strategy: str, *, language: str = "unknown", version: int = 1
    ) -> list[Chunk]:
        sections = self._group_into_sections(doc.structural_elements, language)

        return [
            Chunk(
                id=str(uuid.uuid4()),
                tenant_id=doc.tenant_id,
                document_id=doc.document_id,
                text=section_text,
                position=position,
                language=section_language,
                version=version,
                acl_principals=list(doc.acl_principals),
                metadata={
                    "checksum": doc.checksum,
                    "mime_type": doc.mime_type,
                    "page_number": page_number,
                },
            )
            for position, (section_text, page_number, section_language) in enumerate(sections)
            if section_text.strip()
        ]

    def _group_into_sections(
        self, elements: list[dict[str, Any]], fallback_language: str
    ) -> list[tuple[str, int | None, str]]:
        if not elements:
            return []

        sections: list[tuple[str, int | None, str]] = []
        current_lines: list[str] = []
        current_language_weights: Counter[str] = Counter()
        current_page: int | None = None

        def _flush() -> None:
            section_language = (
                current_language_weights.most_common(1)[0][0]
                if current_language_weights
                else fallback_language
            )
            sections.append(("\n".join(current_lines), current_page, section_language))

        for element in elements:
            text = element.get("text", "")
            if not text:
                continue
            is_heading = element.get("category") in HEADING_CATEGORIES
            if is_heading and current_lines:
                _flush()
                current_lines = []
                current_language_weights = Counter()
                current_page = None
            if current_page is None:
                current_page = element.get("page_number")
            current_lines.append(text)
            current_language_weights[element.get("detected_language", fallback_language)] += len(
                text
            )

        if current_lines:
            _flush()

        return sections
