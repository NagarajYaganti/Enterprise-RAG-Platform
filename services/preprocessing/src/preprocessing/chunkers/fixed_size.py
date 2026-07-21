import uuid

from core.interfaces import Chunker
from core.models import Chunk, ParsedDocument

from preprocessing.tokenization import decode, encode

# cl100k_base (preprocessing.tokenization) is a practical, lightweight
# token-count proxy -- not vocab-identical to the embedding model's own
# tokenizer (pulling sentence-transformers/transformers into this service
# just to count tokens would be a large, disproportionate dependency
# footprint for a different service than the one that actually embeds),
# but verified empirically that it demonstrably fixes the actual problem
# the spec names: 500 characters of Chinese text encodes to far more
# tokens than 500 characters of English, so character-based sizing
# produces wildly inconsistent real chunk sizes across scripts.


class FixedSizeChunker(Chunker):
    """Chunker adapter: fixed-size windows over raw_text with overlap,
    sized in TOKENS, not characters.
    """

    def __init__(self, chunk_size: int = 500, overlap: int = 50) -> None:
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        self._chunk_size = chunk_size
        self._overlap = overlap

    def chunk(
        self, doc: ParsedDocument, strategy: str, *, language: str = "unknown", version: int = 1
    ) -> list[Chunk]:
        tokens = encode(doc.raw_text)
        step = self._chunk_size - self._overlap
        pieces = []
        start = 0
        while start < len(tokens):
            pieces.append(decode(tokens[start : start + self._chunk_size]))
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
