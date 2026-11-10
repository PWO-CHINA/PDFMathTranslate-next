import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from pdf2zh_next import high_level
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.main import ConfigManager
from pdf2zh_next.config.main import MagicDefault
from pdf2zh_next.config.main import build_args_parser
from pdf2zh_next.config.model import TranslationSettings


def test_default_and_cli_env_toml_mapping(tmp_path, monkeypatch):
    assert TranslationSettings().experimental_cross_page_context is False
    parser, types = build_args_parser()
    parsed = {key.replace('-', '_'): value for key, value in vars(parser.parse_args(['--experimental-cross-page-context'])).items() if value is not MagicDefault}
    manager = ConfigManager()
    cli = manager.parse_dict_vars(set(), 0, CLIEnvSettingsModel, parsed)
    assert CLIEnvSettingsModel(**cli).to_settings_model().translation.experimental_cross_page_context
    monkeypatch.setenv('PDF2ZH_EXPERIMENTAL_CROSS_PAGE_CONTEXT', 'true')
    env = manager.parse_env_vars(set(), 0, CLIEnvSettingsModel)
    assert CLIEnvSettingsModel(**env).to_settings_model().translation.experimental_cross_page_context
    config = tmp_path / 'settings.toml'
    config.write_text('[translation]\nexperimental_cross_page_context = true\n', encoding='utf-8')
    toml = manager._read_toml_file(config)
    assert CLIEnvSettingsModel(**toml).to_settings_model().translation.experimental_cross_page_context


@pytest.mark.parametrize('enabled', [False, True])
def test_constructor_receives_only_enabled_setting(monkeypatch, enabled):
    calls = []
    omitted = object()

    def constructor(*, experimental_cross_page_context=omitted, **_kwargs):
        calls.append(experimental_cross_page_context)
        return SimpleNamespace()

    monkeypatch.setattr(high_level, 'BabelDOCConfig', constructor)
    if enabled:
        monkeypatch.setattr(high_level, 'supports_experimental_cross_page_context', lambda: True)
    else:
        monkeypatch.setattr(high_level, 'supports_experimental_cross_page_context', lambda: pytest.fail('disabled option checked compatibility'))
    monkeypatch.setattr(high_level, 'get_translator', lambda _settings: object())
    monkeypatch.setattr(high_level, 'get_term_translator', lambda _settings: object())
    monkeypatch.setattr(high_level, '_get_glossaries', lambda _settings: [])
    settings = CLIEnvSettingsModel(translation={'experimental_cross_page_context': enabled}, pdf={'translate_table_text': False}).to_settings_model()
    high_level.create_babeldoc_config(settings, Path('synthetic.pdf'))
    assert calls == [True if enabled else omitted]


def test_old_constructor_works_when_disabled_and_fails_clearly_when_enabled(monkeypatch):
    calls = []

    def old_constructor(**kwargs):
        assert 'experimental_cross_page_context' not in kwargs
        calls.append(True)
        return SimpleNamespace()

    monkeypatch.setattr(high_level, 'BabelDOCConfig', old_constructor)
    monkeypatch.setattr(high_level, 'get_translator', lambda _settings: object())
    monkeypatch.setattr(high_level, 'get_term_translator', lambda _settings: object())
    monkeypatch.setattr(high_level, '_get_glossaries', lambda _settings: [])
    settings = CLIEnvSettingsModel(pdf={'translate_table_text': False}).to_settings_model()
    high_level.create_babeldoc_config(settings, Path('synthetic.pdf'))
    settings.translation.experimental_cross_page_context = True
    with pytest.raises(RuntimeError, match='installed BabelDOC does not support experimental cross-page context'):
        high_level.create_babeldoc_config(settings, Path('synthetic.pdf'))
    assert len(calls) == 1


@pytest.mark.parametrize(
    ('python_protocol', 'native_protocol', 'expected'),
    [(1, 1, True), (None, 1, False), (1, None, False), (1, 2, False),
     (2, 1, False), (True, 1, False), (1, True, False), ('1', 1, False)],
)
def test_cross_page_protocol_requires_matching_python_and_native_markers(
    monkeypatch, python_protocol, native_protocol, expected
):
    from babeldoc import _rust_il
    from babeldoc.format.pdf import translation_config

    def constructor(*, experimental_cross_page_context=False):
        pass

    monkeypatch.setattr(high_level, 'BabelDOCConfig', constructor)
    monkeypatch.setattr(translation_config, 'CROSS_PAGE_SENTENCE_PROTOCOL_VERSION', python_protocol, raising=False)
    monkeypatch.setattr(_rust_il, 'CROSS_PAGE_SENTENCE_PROTOCOL_VERSION', native_protocol, raising=False)
    assert high_level.supports_experimental_cross_page_context() is expected


@pytest.mark.parametrize('signature', ['missing', 'positional_only', 'keyword_only'])
def test_cross_page_protocol_requires_keyword_parameter(monkeypatch, signature):
    from babeldoc import _rust_il
    from babeldoc.format.pdf import translation_config

    def missing(**kwargs):
        pass

    def positional_only(experimental_cross_page_context=False, /):
        pass

    def keyword_only(*, experimental_cross_page_context=False):
        pass

    constructors = {'missing': missing, 'positional_only': positional_only, 'keyword_only': keyword_only}
    monkeypatch.setattr(high_level, 'BabelDOCConfig', constructors[signature])
    monkeypatch.setattr(translation_config, 'CROSS_PAGE_SENTENCE_PROTOCOL_VERSION', 1, raising=False)
    monkeypatch.setattr(_rust_il, 'CROSS_PAGE_SENTENCE_PROTOCOL_VERSION', 1, raising=False)
    assert high_level.supports_experimental_cross_page_context() is (signature == 'keyword_only')


def test_incompatible_engine_is_rejected_before_translator_initialization(monkeypatch):
    monkeypatch.setattr(high_level, 'supports_experimental_cross_page_context', lambda: False)
    monkeypatch.setattr(high_level, 'get_translator', lambda _settings: pytest.fail('translator initialized'))
    settings = CLIEnvSettingsModel(translation={'experimental_cross_page_context': True}).to_settings_model()
    with pytest.raises(RuntimeError, match='required Python and native sentence protocol'):
        high_level.create_babeldoc_config(settings, Path('synthetic.pdf'))


def test_debug_stream_forwards_enabled_setting_to_babeldoc(tmp_path, monkeypatch):
    source = tmp_path / 'synthetic.pdf'
    source.write_bytes(b'%PDF-1.4')
    calls = []

    async def engine(*, translation_config):
        calls.append(translation_config)
        yield {'type': 'finish'}

    monkeypatch.setattr(high_level, 'get_translator', lambda _settings: object())
    monkeypatch.setattr(high_level, 'get_term_translator', lambda _settings: object())
    monkeypatch.setattr(high_level, '_get_glossaries', lambda _settings: [])
    monkeypatch.setattr(high_level, 'babeldoc_translate', engine)
    monkeypatch.setattr(high_level, 'supports_experimental_cross_page_context', lambda: True)
    settings = CLIEnvSettingsModel(
        basic={'debug': True},
        translation={'experimental_cross_page_context': True},
        pdf={'translate_table_text': False},
    ).to_settings_model()
    monkeypatch.setattr(type(settings), 'validate_settings', lambda _settings: None)

    async def consume():
        return [event async for event in high_level.do_translate_async_stream(settings, source)]

    assert asyncio.run(consume()) == [{'type': 'finish'}]
    assert len(calls) == 1
    assert calls[0].experimental_cross_page_context is True
    assert calls[0].input_file == source


def test_non_debug_stream_passes_enabled_settings_to_subprocess(tmp_path, monkeypatch):
    source = tmp_path / 'synthetic.pdf'
    source.write_bytes(b'%PDF-1.4')
    calls = []

    async def subprocess_stream(settings, file):
        calls.append((settings.translation.experimental_cross_page_context, file))
        yield {'type': 'finish'}

    monkeypatch.setattr(high_level, '_translate_in_subprocess', subprocess_stream)
    settings = CLIEnvSettingsModel(
        basic={'debug': False},
        translation={'experimental_cross_page_context': True},
    ).to_settings_model()
    monkeypatch.setattr(type(settings), 'validate_settings', lambda _settings: None)

    async def consume():
        return [event async for event in high_level.do_translate_async_stream(settings, source)]

    assert asyncio.run(consume()) == [{'type': 'finish'}]
    assert calls == [(True, source)]


def test_cross_page_subprocess_failure_is_forwarded_without_finish(tmp_path, monkeypatch):
    source = tmp_path / 'synthetic.pdf'
    source.write_bytes(b'%PDF-1.4')

    async def subprocess_stream(settings, file):
        assert settings.translation.experimental_cross_page_context is True
        assert file == source
        yield {'type': 'progress_start'}
        raise high_level.BabeldocError('synthetic failure')

    monkeypatch.setattr(high_level, '_translate_in_subprocess', subprocess_stream)
    settings = CLIEnvSettingsModel(translation={'experimental_cross_page_context': True}).to_settings_model()
    monkeypatch.setattr(type(settings), 'validate_settings', lambda _settings: None)

    async def consume():
        events = []
        with pytest.raises(high_level.BabeldocError, match='synthetic failure'):
            async for event in high_level.do_translate_async_stream(settings, source):
                events.append(event)
        return events

    events = asyncio.run(consume())
    assert [event['type'] for event in events] == ['progress_start', 'error']
    assert 'synthetic failure' in events[-1]['error']


def test_cross_page_subprocess_cancellation_runs_cleanup(tmp_path, monkeypatch):
    source = tmp_path / 'synthetic.pdf'
    source.write_bytes(b'%PDF-1.4')
    settings = CLIEnvSettingsModel(translation={'experimental_cross_page_context': True}).to_settings_model()
    monkeypatch.setattr(type(settings), 'validate_settings', lambda _settings: None)

    async def consume_and_cancel():
        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def subprocess_stream(received_settings, file):
            assert received_settings.translation.experimental_cross_page_context is True
            assert file == source
            try:
                started.set()
                await asyncio.Event().wait()
                yield {'type': 'finish'}
            finally:
                cleaned.set()

        monkeypatch.setattr(high_level, '_translate_in_subprocess', subprocess_stream)

        async def consume():
            return [event async for event in high_level.do_translate_async_stream(settings, source)]

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()

    asyncio.run(consume_and_cancel())
