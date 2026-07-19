from core.interfaces import Chunker, Translator
from core.models import Chunk, ParsedDocument

from preprocessing.cleaning import clean_text
from preprocessing.language_detect import LanguageDetector
from preprocessing.metadata import extract_metadata


def run_pipeline(
    doc: ParsedDocument,
    chunker: Chunker,
    strategy: str,
    language_detector: LanguageDetector,
    translator: Translator,
    version: int,
    target_language: str | None = None,
) -> list[Chunk]:
    """detect_language -> [translate] -> clean -> chunk -> extract_metadata,
    matching the fixed data flow in docs/ARCHITECTURE.md.
    """
    language = language_detector.detect(doc.raw_text)

    text = doc.raw_text
    if target_language is not None and language != target_language:
        text = translator.translate(text, language, target_language)
        language = target_language

    cleaned_doc = doc.model_copy(update={"raw_text": clean_text(text)})

    chunks = chunker.chunk(cleaned_doc, strategy, language=language, version=version)

    extra_metadata = extract_metadata(doc, language)
    for chunk in chunks:
        chunk.metadata.update(extra_metadata)

    return chunks
