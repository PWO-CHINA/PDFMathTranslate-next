import hashlib
import sys
from importlib.metadata import version
from pathlib import Path

from security_contract import deny_external_network
from security_contract import isolated_environment


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"baseline", "release"}:
        raise SystemExit("expected baseline or release")
    mode = sys.argv[1]
    with isolated_environment():
        deny_external_network()
        from pdf2zh_next.high_level import supports_experimental_cross_page_context

        if mode == "baseline":
            assert not supports_experimental_cross_page_context()
            return

        from babeldoc import _rust_il
        from babeldoc.format.pdf import translation_config
        from pdf2zh_next.config.model import TranslationSettings

        markers = (
            translation_config.CROSS_PAGE_SENTENCE_PROTOCOL_VERSION,
            _rust_il.CROSS_PAGE_SENTENCE_PROTOCOL_VERSION,
        )
        assert version("BabelDOC") == "0.7.1+pwo.2.crosspage.17"
        assert all(type(value) is int and value == 1 for value in markers)
        assert supports_experimental_cross_page_context() is True
        assert TranslationSettings().experimental_cross_page_context is False
        assert _rust_il.stage_capture_enabled() is False
        assert hashlib.sha256(Path(_rust_il.__file__).read_bytes()).hexdigest() == (
            "ee804d4e686faca9e72725ad0b279649a3ebbee1c027be20939b0f0527e9e938"
        )


if __name__ == "__main__":
    main()
