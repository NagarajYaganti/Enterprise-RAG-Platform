import re
import unicodedata

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_WHITESPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    # NFC, not NFKC: NFKC's compatibility folding silently rewrites
    # meaningful characters (e.g. full-width "１２３" -> ASCII "123"),
    # which breaks citation fidelity to the source text (Global-First
    # principle, docs/ARCHITECTURE.md) -- verified empirically that NFC
    # preserves full-width digits while NFKC does not.
    text = unicodedata.normalize("NFC", text)
    text = _CONTROL_CHARS_RE.sub("", text)
    text = _MULTI_WHITESPACE_RE.sub(" ", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()
