from core.interfaces import Translator


class StubTranslator(Translator):
    """Phase-1 stub: returns text unchanged. Task text explicitly allows a
    stub here ("optional translation step behind a Translator interface
    (stub OK this phase)"). A real provider adapter is future work.
    """

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        return text
