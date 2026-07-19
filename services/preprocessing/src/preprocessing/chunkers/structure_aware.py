import uuid
from typing import Any

from core.interfaces import Chunker
from core.models import Chunk, ParsedDocument

HEADING_CATEGORIES = frozenset({"Title", "Header"})


class StructureAwareChunker(Chunker):
    """Chunker adapter: splits on heading/title boundaries from
    ParsedDocument.structural_elements, keeping each section (heading + the
    text under it until the next heading) as one chunk.
    """

    def chunk(
        self, doc: ParsedDocument, strategy: str, *, language: str = "unknown", version: int = 1
    ) -> list[Chunk]:
        sections = self._group_into_sections(doc.structural_elements)

        return [
            Chunk(
                id=str(uuid.uuid4()),
                tenant_id=doc.tenant_id,
                document_id=doc.document_id,
                text=section_text,
                position=position,
                language=language,
                version=version,
                acl_principals=list(doc.acl_principals),
                metadata={
                    "checksum": doc.checksum,
                    "mime_type": doc.mime_type,
                    "page_number": page_number,
                },
            )
            for position, (section_text, page_number) in enumerate(sections)
            if section_text.strip()
        ]

    def _group_into_sections(
        self, elements: list[dict[str, Any]]
    ) -> list[tuple[str, int | None]]:
        if not elements:
            return []

        sections: list[tuple[str, int | None]] = []
        current_lines: list[str] = []
        current_page: int | None = None

        for element in elements:
            text = element.get("text", "")
            if not text:
                continue
            is_heading = element.get("category") in HEADING_CATEGORIES
            if is_heading and current_lines:
                sections.append(("\n".join(current_lines), current_page))
                current_lines = []
                current_page = None
            if current_page is None:
                current_page = element.get("page_number")
            current_lines.append(text)

        if current_lines:
            sections.append(("\n".join(current_lines), current_page))

        return sections
