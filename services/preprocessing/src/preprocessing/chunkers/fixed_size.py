import uuid

from core.interfaces import Chunker
from core.models import Chunk, ParsedDocument


class FixedSizeChunker(Chunker):
    """Chunker adapter: fixed-size windows over raw_text with overlap."""

    def __init__(self, chunk_size: int = 500, overlap: int = 50) -> None:
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        self._chunk_size = chunk_size
        self._overlap = overlap

    def chunk(
        self, doc: ParsedDocument, strategy: str, *, language: str = "unknown", version: int = 1
    ) -> list[Chunk]:
        text = doc.raw_text
        step = self._chunk_size - self._overlap
        pieces = []
        start = 0
        while start < len(text):
            pieces.append(text[start : start + self._chunk_size])
            start += step

        return [
            Chunk(
                id=str(uuid.uuid4()),
                tenant_id=doc.tenant_id,
                document_id=doc.document_id,
                text=piece,
                position=position,
                language=language,
                version=version,
                acl_principals=list(doc.acl_principals),
                metadata={"checksum": doc.checksum, "mime_type": doc.mime_type},
            )
            for position, piece in enumerate(pieces)
            if piece.strip()
        ]
