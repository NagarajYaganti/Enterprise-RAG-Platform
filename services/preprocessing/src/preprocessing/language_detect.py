from lingua import Language, LanguageDetectorBuilder

# A fixed, documented subset rather than from_all_languages(): the full set
# (75 languages) is slower to build and more prone to misclassifying short
# text against similar languages. This list covers the languages relevant to
# the BFSI/Retail/Healthcare anchor customers this platform targets;
# revisit if a customer needs a language outside this set.
SUPPORTED_LANGUAGES = [
    Language.ENGLISH,
    Language.SPANISH,
    Language.FRENCH,
    Language.GERMAN,
    Language.PORTUGUESE,
    Language.HINDI,
    Language.ARABIC,
    Language.CHINESE,
    Language.JAPANESE,
]


class LanguageDetector:
    def __init__(self) -> None:
        self._detector = LanguageDetectorBuilder.from_languages(*SUPPORTED_LANGUAGES).build()

    def detect(self, text: str) -> str:
        language = self._detector.detect_language_of(text)
        if language is None:
            return "unknown"
        return language.iso_code_639_1.name.lower()
