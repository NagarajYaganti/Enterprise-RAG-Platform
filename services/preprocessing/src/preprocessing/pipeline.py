from collections import Counter

from core.interfaces import Chunker, Translator
from core.models import Chunk, ParsedDocument

from preprocessing.cleaning import clean_text
from preprocessing.language_detect import LanguageDetector
from preprocessing.language_policy import decide_language_action
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

    Language is detected per structural element, not once on the whole
    document -- documents mix languages (a real English section followed by
    an Arabic one, say), and detecting once on the concatenated text hides
    that (Global-First principle, docs/ARCHITECTURE.md). Each element in
    doc.structural_elements gets a `detected_language` key that
    StructureAwareChunker reads per-section. A document-level `language` is
    still derived (the majority across elements, or whole-text detection
    when there are no structural elements at all, e.g. plain-text formats
    with no structure) for chunkers with no section granularity to align
    to (FixedSizeChunker) and for extract_metadata's document-level field.
    """
    structural_elements = [dict(element) for element in doc.structural_elements]
    for element in structural_elements:
        element_text = element.get("text", "")
        element["detected_language"] = (
            language_detector.detect(element_text) if element_text else "unknown"
        )

    if structural_elements:
        detected_languages = [e["detected_language"] for e in structural_elements]
        language = Counter(detected_languages).most_common(1)[0][0]
    else:
        language = language_detector.detect(doc.raw_text)

    original_raw_text = doc.raw_text
    text = doc.raw_text
    was_translated = False

    if target_language is not None:
        # Explicit request: honor it unconditionally, same as before
        # LanguagePolicy existed -- the caller deliberately asked for this
        # translation, so the wiring (relabel language, capture
        # original_text) must work even against a no-op stub translator;
        # that is exactly what proves the mechanism is correct.
        if language != target_language:
            text = translator.translate(text, language, target_language)
            was_translated = True
            language = target_language
            for element in structural_elements:
                element["detected_language"] = target_language
    else:
        # No explicit request: LanguagePolicy decides whether this language
        # needs translate-then-embed at all (Section 4 Phase 1: "translate-
        # then-embed for low-resource languages the embedding model handles
        # poorly"). Only trust the result (and relabel `language`) if the
        # translator actually changed the text -- Translator is still a
        # no-op stub, and blindly relabeling untranslated Arabic text as
        # "en" would be a worse bug than not translating at all (a false
        # claim about what language the chunk's text is actually written
        # in). This distinction only matters for the implicit path: an
        # explicit request above is the caller's own deliberate choice.
        action = decide_language_action(language)
        candidate_target = action.get("target_language", "en")
        if action["action"] == "translate_then_embed" and language != candidate_target:
            translated = translator.translate(text, language, candidate_target)
            if translated != text:
                text = translated
                was_translated = True
                language = candidate_target
                for element in structural_elements:
                    element["detected_language"] = candidate_target

    cleaned_doc = doc.model_copy(
        update={"raw_text": clean_text(text), "structural_elements": structural_elements}
    )

    chunks = chunker.chunk(cleaned_doc, strategy, language=language, version=version)

    extra_metadata = extract_metadata(doc, language)
    for chunk in chunks:
        chunk.metadata.update(extra_metadata)
        if was_translated:
            # The original is never replaced, only accompanied (Global-First
            # principle) -- attached at whole-document granularity, not a
            # precise per-chunk original slice: translation currently runs
            # once over the whole raw_text before chunking splits it, so
            # there is no per-chunk original boundary to align to yet (the
            # Translator is still a no-op stub; a real, section-aware
            # translator would be the natural place to make this precise).
            chunk.original_text = original_raw_text

    return chunks
