from preprocessing.language_detect import LanguageDetector


def test_detects_english() -> None:
    detector = LanguageDetector()
    assert detector.detect("The quick brown fox jumps over the lazy dog.") == "en"


def test_detects_spanish() -> None:
    detector = LanguageDetector()
    assert detector.detect("El rápido zorro marrón salta sobre el perro perezoso.") == "es"


def test_detects_french() -> None:
    detector = LanguageDetector()
    assert detector.detect("Le renard brun rapide saute par-dessus le chien paresseux.") == "fr"
